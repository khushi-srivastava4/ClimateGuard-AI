from __future__ import annotations

import logging
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import openai

from app.agent import graph
from app.agent.graph import _call_llm, _extract_gemini_text, _llm_timeout
from app.config import Settings, settings
from app.services import llm_router


class GeminiConfigurationTests(unittest.TestCase):
    def test_default_model_is_a_supported_text_generation_model(self) -> None:
        with patch.dict(os.environ, {"LLM_PROVIDER": "GEMINI"}, clear=True):
            self.assertEqual(Settings().LLM_MODEL, "gemini-2.5-flash")

    def test_model_can_be_overridden_by_environment(self) -> None:
        with patch.dict(
            os.environ,
            {"LLM_PROVIDER": "GEMINI", "LLM_MODEL": "gemini-3.8-flash"},
            clear=True,
        ):
            self.assertEqual(Settings().LLM_MODEL, "gemini-3.8-flash")

    def test_openai_backup_uses_its_own_environment_variables(self) -> None:
        with patch.dict(
            os.environ,
            {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "gpt-4o-mini"},
            clear=True,
        ):
            configured = Settings()

        self.assertEqual(configured.BACKUP_OPENAI_API_KEY, "test-key")
        self.assertEqual(configured.BACKUP_OPENAI_MODEL, "gpt-4o-mini")


class GeminiResponseTests(unittest.TestCase):
    def test_extracts_text_from_multiple_parts(self) -> None:
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "first "}, {"text": "second"}]
                    }
                }
            ]
        }
        self.assertEqual(_extract_gemini_text(payload), "first second")

    def test_missing_candidates_is_malformed(self) -> None:
        with self.assertRaisesRegex(ValueError, "no candidates"):
            _extract_gemini_text({"candidates": []})

    def test_blocked_prompt_is_not_treated_as_advice(self) -> None:
        with self.assertRaisesRegex(ValueError, "blocked the prompt"):
            _extract_gemini_text(
                {"promptFeedback": {"blockReason": "SAFETY"}, "candidates": []}
            )

    def test_blocked_candidate_is_not_treated_as_advice(self) -> None:
        with self.assertRaisesRegex(ValueError, "blocked the candidate"):
            _extract_gemini_text(
                {
                    "candidates": [
                        {
                            "finishReason": "SAFETY",
                            "content": {"parts": []},
                        }
                    ]
                }
            )


class GeminiRequestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings_patch = patch.multiple(
            settings,
            LLM_PROVIDER="GEMINI",
            LLM_API_KEY="test-key-never-log",
            LLM_MODEL="gemini-3.8-flash",
            LLM_CONNECT_TIMEOUT=7.0,
            LLM_READ_TIMEOUT=19.0,
            LLM_WRITE_TIMEOUT=8.0,
            LLM_POOL_TIMEOUT=3.0,
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)

    def make_client_context(self, post: AsyncMock) -> MagicMock:
        client = AsyncMock()
        client.post = post
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=None)
        return context

    async def test_timeout_types_are_logged_and_return_unavailable(self) -> None:
        post = AsyncMock(side_effect=httpx.ReadTimeout("simulated timeout"))
        with patch(
            "app.agent.graph.httpx.AsyncClient",
            return_value=self.make_client_context(post),
        ) as client_factory:
            with self.assertLogs("app.agent.graph", level=logging.ERROR) as captured:
                result = await _call_llm("prompt", "data", "en")

        self.assertIn("advisory is unavailable", result)
        self.assertIn("response timed out while waiting", captured.output[0])
        self.assertNotIn("test-key-never-log", "\n".join(captured.output))
        timeout = client_factory.call_args.kwargs["timeout"]
        self.assertEqual(timeout.connect, 7.0)
        self.assertEqual(timeout.read, 15.0)
        self.assertEqual(timeout.write, 5.0)
        self.assertEqual(timeout.pool, 2.0)

    def test_llm_timeout_components_are_bounded(self) -> None:
        settings.LLM_CONNECT_TIMEOUT = 60.0
        settings.LLM_READ_TIMEOUT = 60.0
        settings.LLM_WRITE_TIMEOUT = 60.0
        settings.LLM_POOL_TIMEOUT = 60.0

        timeout = _llm_timeout()

        self.assertEqual(timeout.connect, 8.0)
        self.assertEqual(timeout.read, 15.0)
        self.assertEqual(timeout.write, 5.0)
        self.assertEqual(timeout.pool, 2.0)

    async def test_connection_timeout_is_distinguished(self) -> None:
        post = AsyncMock(side_effect=httpx.ConnectTimeout("simulated timeout"))
        with patch(
            "app.agent.graph.httpx.AsyncClient",
            return_value=self.make_client_context(post),
        ):
            with self.assertLogs("app.agent.graph", level=logging.ERROR) as captured:
                result = await _call_llm("prompt", "data", "en")

        self.assertIn("advisory is unavailable", result)
        self.assertIn("connection timed out before reaching", captured.output[0])

    async def test_request_uses_google_endpoint_header_and_payload(self) -> None:
        response = MagicMock()
        response.is_error = False
        response.json.return_value = {
            "candidates": [
                {"content": {"parts": [{"text": "Generated advisory"}]}}
            ]
        }
        post = AsyncMock(return_value=response)
        with patch(
            "app.agent.graph.httpx.AsyncClient",
            return_value=self.make_client_context(post),
        ):
            result = await _call_llm("system prompt", "actual data", "en")

        self.assertEqual(result, "Generated advisory")
        args, kwargs = post.call_args
        self.assertEqual(
            args[0],
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-3.8-flash:generateContent",
        )
        self.assertEqual(kwargs["headers"]["x-goog-api-key"], settings.LLM_API_KEY)
        self.assertEqual(
            kwargs["json"]["systemInstruction"]["parts"][0]["text"],
            "system prompt",
        )
        self.assertEqual(
            kwargs["json"]["contents"][0]["parts"][0]["text"], "actual data"
        )

    async def test_openai_request_uses_bearer_authentication(self) -> None:
        settings.LLM_PROVIDER = "OPENAI"
        settings.LLM_MODEL = "gpt-4o-mini"
        response = MagicMock()
        response.is_error = False
        response.json.return_value = {
            "choices": [{"message": {"content": "Generated advisory"}}]
        }
        post = AsyncMock(return_value=response)
        with patch(
            "app.agent.graph.httpx.AsyncClient",
            return_value=self.make_client_context(post),
        ):
            result = await _call_llm("system prompt", "actual data", "en")

        self.assertEqual(result, "Generated advisory")
        args, kwargs = post.call_args
        self.assertEqual(args[0], "https://api.openai.com/v1/chat/completions")
        self.assertEqual(
            kwargs["headers"]["Authorization"],
            "Bearer test-key-never-log",
        )

    async def test_http_error_is_logged_with_sanitized_message(self) -> None:
        response = MagicMock()
        response.is_error = True
        response.status_code = 403
        response.json.return_value = {
            "error": {"message": "Rejected key test-key-never-log"}
        }
        post = AsyncMock(return_value=response)
        with patch(
            "app.agent.graph.httpx.AsyncClient",
            return_value=self.make_client_context(post),
        ):
            with self.assertLogs("app.agent.graph", level=logging.ERROR) as captured:
                result = await _call_llm("prompt", "data", "en")

        logs = "\n".join(captured.output)
        self.assertIn("HTTP 403", logs)
        self.assertIn("[redacted]", logs)
        self.assertNotIn("test-key-never-log", logs)
        self.assertIn("advisory is unavailable", result)

    async def test_transient_service_error_is_retried(self) -> None:
        busy_response = MagicMock()
        busy_response.is_error = True
        busy_response.status_code = 503
        busy_response.headers = {"Retry-After": "0"}
        busy_response.json.return_value = {
            "error": {"message": "Model is temporarily busy."}
        }
        success_response = MagicMock()
        success_response.is_error = False
        success_response.json.return_value = {
            "candidates": [
                {"content": {"parts": [{"text": "Recovered advisory"}]}}
            ]
        }
        post = AsyncMock(side_effect=[busy_response, success_response])
        with patch(
            "app.agent.graph.httpx.AsyncClient",
            return_value=self.make_client_context(post),
        ):
            result = await _call_llm("prompt", "data", "en")

        self.assertEqual(result, "Recovered advisory")
        self.assertEqual(post.await_count, 2)

    async def test_quota_exhaustion_is_not_retried(self) -> None:
        response = MagicMock()
        response.status_code = 429
        response.is_error = True
        response.json.return_value = {
            "error": {"message": "You exceeded your current quota."}
        }
        post = AsyncMock(return_value=response)
        with patch(
            "app.agent.graph.httpx.AsyncClient",
            return_value=self.make_client_context(post),
        ):
            with self.assertLogs("app.agent.graph", level=logging.ERROR) as captured:
                result = await _call_llm("prompt", "data", "en")

        self.assertIn("advisory is unavailable", result)
        self.assertEqual(post.await_count, 1)
        self.assertIn("quota", captured.output[-1].lower())

    async def test_malformed_response_returns_unavailable(self) -> None:
        response = MagicMock()
        response.is_error = False
        response.json.return_value = {"candidates": []}
        post = AsyncMock(return_value=response)
        with patch(
            "app.agent.graph.httpx.AsyncClient",
            return_value=self.make_client_context(post),
        ):
            with self.assertLogs("app.agent.graph", level=logging.ERROR):
                result = await _call_llm("prompt", "data", "en")

        self.assertIn("advisory is unavailable", result)


class OpenAIBackupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.settings_patch = patch.multiple(
            settings,
            LLM_PROVIDER="GEMINI",
            LLM_API_KEY="gemini-test-key",
            LLM_MODEL="gemini-2.5-flash",
            BACKUP_OPENAI_API_KEY="openai-test-key",
            BACKUP_OPENAI_MODEL="gpt-4o-mini",
            BACKUP_ANTHROPIC_API_KEY="",
            BACKUP_GROQ_API_KEY="",
            BACKUP_GEMINI_API_KEY="",
        )
        self.settings_patch.start()
        self.addCleanup(self.settings_patch.stop)
        llm_router.COOLDOWN.clear()
        llm_router.CACHE.clear()
        self.addCleanup(llm_router.COOLDOWN.clear)
        self.addCleanup(llm_router.CACHE.clear)

    async def test_gemini_success_does_not_call_backup(self) -> None:
        with (
            patch("app.agent.graph.cache.get", return_value=None),
            patch("app.agent.graph.cache.set"),
            patch(
                "app.agent.graph._call_llm",
                new=AsyncMock(return_value="Gemini advisory"),
            ),
            patch(
                "app.agent.graph.llm_router.generate",
                new=AsyncMock(),
            ) as backup,
        ):
            result = await graph._advise_text("system prompt", "field data", "en", {})

        self.assertEqual(result, ("Gemini advisory", "generated", "gemini"))
        backup.assert_not_awaited()

    async def test_gemini_quota_failure_falls_back_to_openai(self) -> None:
        primary = AsyncMock(return_value=graph._advisory_unavailable("en"))

        async def openai_call(provider, prompt, system):
            self.assertEqual(provider["kind"], "OPENAI")
            self.assertEqual(provider["model"], "gpt-4o-mini")
            self.assertEqual(prompt, "field data")
            self.assertEqual(system, "system prompt")
            return "OpenAI advisory"

        with (
            patch("app.agent.graph.cache.get", return_value=None),
            patch("app.agent.graph.cache.set"),
            patch("app.agent.graph._call_llm", new=primary),
            patch.object(llm_router, "_call", side_effect=openai_call) as provider_call,
        ):
            result = await graph._advise_text("system prompt", "field data", "en", {})

        self.assertEqual(result, ("OpenAI advisory", "generated", "openai-backup"))
        primary.assert_awaited_once()
        self.assertEqual(provider_call.await_count, 1)

    async def test_missing_openai_credentials_are_reported(self) -> None:
        settings.BACKUP_OPENAI_API_KEY = ""
        with (
            patch("app.agent.graph.cache.get", return_value=None),
            patch("app.agent.graph.cache.set"),
            patch(
                "app.agent.graph._call_llm",
                new=AsyncMock(return_value=graph._advisory_unavailable("en")),
            ),
            patch.object(llm_router, "providers", return_value=[]),
        ):
            with self.assertLogs("app.agent.graph", level=logging.WARNING) as captured:
                result = await graph._advise_text(
                    "missing-key-system", "field data", "en", {"risk": {}}
                )

        self.assertEqual(result[1:], ("unavailable", "none"))
        self.assertIn("OPENAI_API_KEY is not configured", "\n".join(captured.output))
        self.assertNotIn("openai-test-key", "\n".join(captured.output))

    async def test_openai_failure_retains_rules_based_fallback(self) -> None:
        async def failed_openai(provider, prompt, system):
            raise llm_router.ProviderError("insufficient API credits or quota", 429)

        with (
            patch("app.agent.graph.cache.get", return_value=None),
            patch("app.agent.graph.cache.set"),
            patch(
                "app.agent.graph._call_llm",
                new=AsyncMock(return_value=graph._advisory_unavailable("en")),
            ),
            patch.object(llm_router, "_call", side_effect=failed_openai),
        ):
            with self.assertLogs("app.agent.graph", level=logging.WARNING) as captured:
                result = await graph._advise_text(
                    "both-failed-system",
                    "field data",
                    "en",
                    {"risk": {"reasons": ["Rainfall risk is high."]}},
                )

        self.assertEqual(result[1:], ("fallback", "rules"))
        self.assertIn("Rule-based summary", result[0])
        self.assertIn("insufficient API credits or quota", "\n".join(captured.output))

    async def test_openai_sdk_request_uses_prompt_and_returns_text(self) -> None:
        response = SimpleNamespace(
            choices=[
                SimpleNamespace(message=SimpleNamespace(content="OpenAI generated advisory"))
            ]
        )
        create = AsyncMock(return_value=response)
        client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        context = MagicMock()
        context.__aenter__ = AsyncMock(return_value=client)
        context.__aexit__ = AsyncMock(return_value=None)
        provider = {
            "kind": "OPENAI",
            "key": "openai-test-key",
            "model": "gpt-4o-mini",
        }

        with patch("app.services.llm_router.AsyncOpenAI", return_value=context) as factory:
            result = await llm_router._call(provider, "retrieved field info", "same system prompt")

        self.assertEqual(result, "OpenAI generated advisory")
        self.assertEqual(factory.call_args.kwargs["api_key"], "openai-test-key")
        self.assertEqual(
            create.call_args.kwargs["messages"],
            [
                {"role": "system", "content": "same system prompt"},
                {"role": "user", "content": "retrieved field info"},
            ],
        )
        self.assertEqual(create.call_args.kwargs["model"], "gpt-4o-mini")

    async def test_gemini_primary_and_backup_are_both_skipped_after_quota_failure(self) -> None:
        settings.BACKUP_GEMINI_API_KEY = "different-gemini-key"
        called = []

        async def openai_only(provider, prompt, system):
            called.append(provider["kind"])
            return "OpenAI answer"

        with patch.object(llm_router, "_call", side_effect=openai_only):
            result = await llm_router.generate(
                "unique failover prompt",
                "system",
                skip=["gemini"],
                use_cache=False,
            )

        self.assertEqual(result["provider"], "openai-backup")
        self.assertEqual(called, ["OPENAI"])

    def test_openai_provider_errors_are_safe_and_specific(self) -> None:
        request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
        response = httpx.Response(
            429,
            headers={"retry-after": "15"},
            request=request,
        )
        error = openai.RateLimitError(
            "sensitive provider body",
            response=response,
            body={"error": {"code": "insufficient_quota", "message": "sensitive detail"}},
        )

        translated = llm_router._openai_provider_error(error)

        self.assertEqual(translated.status, 429)
        self.assertEqual(translated.retry_after, 15)
        self.assertEqual(str(translated), "insufficient API credits or quota")
        self.assertNotIn("sensitive", str(translated))

        auth_error = openai.AuthenticationError(
            "sensitive provider body",
            response=httpx.Response(401, request=request),
            body={"error": {"message": "sensitive detail"}},
        )
        self.assertEqual(
            str(llm_router._openai_provider_error(auth_error)),
            "invalid API key",
        )


@unittest.skipUnless(
    os.getenv("CLIMATEGUARD_LIVE_OPENAI_MODEL_TEST") == "1",
    "Set CLIMATEGUARD_LIVE_OPENAI_MODEL_TEST=1 to verify OpenAI model access.",
)
class LiveOpenAIModelAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_configured_model_is_available_to_api_account(self) -> None:
        if not settings.BACKUP_OPENAI_API_KEY.strip():
            self.skipTest("OPENAI_API_KEY is not configured.")

        from openai import AsyncOpenAI

        async with AsyncOpenAI(
            api_key=settings.BACKUP_OPENAI_API_KEY,
            timeout=_llm_timeout(),
        ) as client:
            model = await client.models.retrieve(settings.BACKUP_OPENAI_MODEL)
        self.assertEqual(model.id, settings.BACKUP_OPENAI_MODEL)


@unittest.skipUnless(
    os.getenv("CLIMATEGUARD_LIVE_GEMINI_TEST") == "1",
    "Set CLIMATEGUARD_LIVE_GEMINI_TEST=1 to call Gemini.",
)
class LiveGeminiIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_configured_model_can_generate_content(self) -> None:
        if settings.LLM_PROVIDER != "GEMINI" or not settings.LLM_API_KEY.strip():
            self.skipTest("Gemini provider and API key are not configured.")

        timeout = _llm_timeout()
        async with httpx.AsyncClient(timeout=timeout) as client:
            models_response = await client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": settings.LLM_API_KEY},
                params={"pageSize": 1000},
            )
            models_response.raise_for_status()
            models = models_response.json().get("models", [])
            available = any(
                item.get("name", "").removeprefix("models/") == settings.LLM_MODEL
                and "generateContent"
                in item.get("supportedGenerationMethods", [])
                for item in models
                if isinstance(item, dict)
            )
            self.assertTrue(
                available,
                f"Configured model {settings.LLM_MODEL!r} does not support generateContent for this key.",
            )

        with self.assertLogs("app.agent.graph", level=logging.ERROR) as captured:
            result = await _call_llm("Reply with exactly OK.", "Say OK.", "en")
        if "AI-generated advisory is unavailable" in result:
            messages = "\n".join(captured.output).lower()
            if "http 429" in messages and "quota" in messages:
                self.skipTest(
                    "Gemini model access is confirmed, but the API key's generation quota is exhausted."
                )
            self.fail(f"Gemini generation failed; check the sanitized backend log: {captured.output}")
        self.assertTrue(
            result.strip(),
            "Gemini returned no generated text; check the sanitized backend log.",
        )
        self.assertNotIn("AI-generated advisory is unavailable", result)


if __name__ == "__main__":
    unittest.main()
