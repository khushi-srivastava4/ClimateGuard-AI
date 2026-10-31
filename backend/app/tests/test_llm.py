from __future__ import annotations

import logging
import os
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx

from app.agent.graph import _call_llm, _extract_gemini_text, _llm_timeout
from app.config import Settings, settings


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
