from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sarvamai.core.api_error import ApiError

from app.routers import ops
from app.services import translation_service


class FakeSarvamAI:
    calls = []
    translated_text = "अनुवाद"
    append_input = False
    error = None

    def __init__(self, *, api_subscription_key, timeout):
        assert api_subscription_key == "test-key"
        assert timeout == 30
        self.text = SimpleNamespace(translate=self.translate)

    def translate(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        translated_text = self.translated_text
        if self.append_input:
            translated_text += kwargs["input"]
        return SimpleNamespace(translated_text=translated_text)


@pytest.fixture(autouse=True)
def reset_fake_sarvam(monkeypatch):
    FakeSarvamAI.calls = []
    FakeSarvamAI.translated_text = "अनुवाद"
    FakeSarvamAI.append_input = False
    FakeSarvamAI.error = None
    monkeypatch.setattr(translation_service, "SarvamAI", FakeSarvamAI)
    monkeypatch.setattr(translation_service.settings, "SARVAM_API_KEY", "test-key")


def test_english_advisory_is_returned_unchanged_without_provider_call(monkeypatch) -> None:
    monkeypatch.setattr(translation_service.settings, "SARVAM_API_KEY", "")
    original = "Wheat: irrigate 24 mm on 2026-10-31 [S1]."

    assert asyncio.run(translation_service.translate_advisory(original, "en")) == original
    assert FakeSarvamAI.calls == []


@pytest.mark.parametrize(
    ("target", "target_code", "translated_prefix"),
    [("hi", "hi-IN", "हिंदी"), ("ta", "ta-IN", "தமிழ்")],
)
def test_translation_uses_sarvam_sdk_and_preserves_advisory_details(
    target, target_code, translated_prefix
) -> None:
    FakeSarvamAI.translated_text = f"{translated_prefix}: "
    FakeSarvamAI.append_input = True
    original = (
        "Wheat: irrigate 24 mm on 2026-10-31; risk 46/100 at 32°C; "
        "ET0 x Kc 1.1; ₹200/quintal [S1]."
    )
    translated = asyncio.run(translation_service.translate_advisory(original, target))

    assert translated.startswith(f"{translated_prefix}: ")
    assert "Wheat" in translated
    assert "24 mm" in translated
    assert "2026-10-31" in translated
    assert "46/100" in translated
    assert "32°C" in translated
    assert "ET0" in translated
    assert "Kc" in translated
    assert "₹200/quintal" in translated
    assert "[S1]" in translated
    call = FakeSarvamAI.calls[0]
    assert call["source_language_code"] == "en-IN"
    assert call["target_language_code"] == target_code
    assert call["model"] == "sarvam-translate:v1"
    assert call["mode"] == "formal"
    assert call["numerals_format"] == "international"
    assert "Wheat" not in call["input"]
    assert "[S1]" not in call["input"]


def test_odia_uses_sarvams_od_language_code() -> None:
    FakeSarvamAI.translated_text = "ଓଡ଼ିଆ ଅନୁବାଦ"

    translated = asyncio.run(translation_service.translate_advisory("A forecast.", "or"))

    assert translated == "ଓଡ଼ିଆ ଅନୁବାଦ"
    assert FakeSarvamAI.calls[0]["target_language_code"] == "od-IN"


def test_requested_languages_map_to_sarvam_api_codes() -> None:
    assert {
        language: details[1]
        for language, details in translation_service.SUPPORTED_LANGUAGES.items()
    } == {
        "en": "en-IN",
        "hi": "hi-IN",
        "bn": "bn-IN",
        "ta": "ta-IN",
        "te": "te-IN",
        "mr": "mr-IN",
        "gu": "gu-IN",
        "kn": "kn-IN",
        "ml": "ml-IN",
        "pa": "pa-IN",
        "or": "od-IN",
        "as": "as-IN",
        "ur": "ur-IN",
    }


def test_missing_credentials_are_reported_by_translate_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(translation_service.settings, "SARVAM_API_KEY", "")
    app = FastAPI()
    app.include_router(ops.router)

    response = TestClient(app).post(
        "/assistant/translate",
        json={"text": "Irrigate 24 mm [S1].", "target_language": "hi"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Translation is not configured. Set SARVAM_API_KEY on the backend."
    )
    assert "test-key" not in response.text


def test_provider_quota_failure_is_clear_and_does_not_return_english() -> None:
    FakeSarvamAI.error = ApiError(status_code=429, body={"message": "private provider detail"})
    app = FastAPI()
    app.include_router(ops.router)

    response = TestClient(app).post(
        "/assistant/translate",
        json={"text": "Rule-based advisory: irrigate 24 mm [S1].", "target_language": "hi"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Translation service quota or credits are unavailable. Please try again later."
    )
    assert "private provider detail" not in response.text
    assert "Rule-based advisory" not in response.text


def test_translation_timeout_has_a_clear_error() -> None:
    FakeSarvamAI.error = httpx.ReadTimeout("private timeout detail")
    app = FastAPI()
    app.include_router(ops.router)

    response = TestClient(app).post(
        "/assistant/translate",
        json={"text": "Forecast.", "target_language": "hi"},
    )

    assert response.status_code == 504
    assert response.json()["detail"] == "Translation timed out. Please try again."


def test_chat_translates_rule_based_advisory_without_changing_history(monkeypatch) -> None:
    FakeSarvamAI.translated_text = "हिंदी सलाह: "
    FakeSarvamAI.append_input = True
    advisory = "Rule-based advisory: irrigate 24 mm on 2026-10-31 [S1]."
    captured = {}

    async def fake_build(*args):
        return {
            "soil": None,
            "enso": None,
            "market": None,
            "actions_v2": [],
            "sources": [],
            "warnings": [],
        }

    async def fake_advise(summary, language, question, history):
        captured["language"] = language
        captured["history"] = history
        return {
            "advisory": advisory,
            "generated_by": {"fallback": True},
            "grounding": None,
        }

    monkeypatch.setattr(ops, "build", fake_build)
    monkeypatch.setattr(ops.advisory_service, "build_summary", lambda *args: {})
    monkeypatch.setattr(ops.advisory_service, "advise", fake_advise)
    app = FastAPI()
    app.include_router(ops.router)

    response = TestClient(app).post(
        "/assistant/chat",
        json={
            "lat": 27.1,
            "lon": 78.0,
            "language": "hi",
            "message": "Should I irrigate?",
            "history": [{"role": "assistant", "content": "Previous English advisory."}],
        },
    )

    assert response.status_code == 200
    assert response.json()["source_advisory"] == advisory
    assert response.json()["advisory"].startswith("हिंदी सलाह: ")
    assert "24 mm" in response.json()["advisory"]
    assert "2026-10-31" in response.json()["advisory"]
    assert "[S1]" in response.json()["advisory"]
    assert response.json()["generated_by"]["fallback"] is True
    assert captured == {
        "language": "en",
        "history": [{"role": "assistant", "content": "Previous English advisory."}],
    }
    assert FakeSarvamAI.calls[0]["target_language_code"] == "hi-IN"


def test_empty_provider_translation_is_rejected() -> None:
    FakeSarvamAI.translated_text = "  "

    with pytest.raises(translation_service.TranslationError, match="empty translation"):
        asyncio.run(translation_service.translate_advisory("Forecast.", "hi"))


def test_unchanged_english_provider_response_is_rejected() -> None:
    FakeSarvamAI.translated_text = "Forecast."

    with pytest.raises(translation_service.TranslationError, match="original English"):
        asyncio.run(translation_service.translate_advisory("Forecast.", "hi"))


def test_chat_accepts_all_sarvam_translation_codes() -> None:
    from app.routers.ops import ChatRequest

    codes = ("en", "hi", "bn", "ta", "te", "mr", "gu", "kn", "ml", "pa", "or", "as", "ur")
    for code in codes:
        request = ChatRequest(lat=27.1, lon=78.0, language=code, message="question")
        assert request.language == code
