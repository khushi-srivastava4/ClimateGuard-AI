from __future__ import annotations

import io
import wave
from pathlib import Path

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import voice


def voice_client(monkeypatch) -> TestClient:
    monkeypatch.setattr(voice.settings, "GNANI_API_KEY", "test-api-key")
    app = FastAPI()
    app.include_router(voice.router)
    return TestClient(app)


def test_capabilities_report_separate_verified_services() -> None:
    app = FastAPI()
    app.include_router(voice.router)
    client = TestClient(app)
    response = client.get("/voice/capabilities")

    assert response.status_code == 200
    result = response.json()
    assert "ml-IN" in result["stt"]["languages"]
    assert "ml-IN" in result["tts"]["languages"]
    assert result["stt"]["auto_detection_code"] == "indic-auto"
    assert result["tts"]["mime_type"] == "audio/wav"


@pytest.mark.parametrize("language_code", ["en-IN", "hi-IN", "ta-IN"])
def test_stt_returns_transcript_metadata_and_removes_temporary_audio(monkeypatch, language_code) -> None:
    client = voice_client(monkeypatch)
    temp_paths: list[Path] = []

    class FakeSTTClient:
        def __init__(self, api_key):
            assert api_key == "test-api-key"

        def transcribe(self, audio, requested_language, *, model):
            path = Path(audio)
            temp_paths.append(path)
            assert path.read_bytes() == b"recorded audio"
            assert requested_language == language_code
            assert model == voice.PRISMA_V3_MODEL
            return {
                "success": True,
                "transcript": "नमस्ते",
                "detected_language_code": requested_language,
                "model": model,
                "request_id": "request-1",
                "truncated": False,
            }

    monkeypatch.setattr(voice, "GnaniSTTClient", FakeSTTClient)
    response = client.post(
        "/voice/stt",
        data={"language_code": language_code},
        files={"audio": ("recording.wav", b"recorded audio", "audio/wav")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "transcript": "नमस्ते",
        "language_code": language_code,
        "detected_language_code": language_code,
        "model": voice.PRISMA_V3_MODEL,
        "request_id": "request-1",
        "truncated": False,
    }
    assert temp_paths and all(not path.exists() for path in temp_paths)


def test_stt_rejects_empty_audio(monkeypatch) -> None:
    response = voice_client(monkeypatch).post(
        "/voice/stt",
        data={"language_code": "en-IN"},
        files={"audio": ("recording.wav", b"", "audio/wav")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Audio file is empty."


def test_stt_rejects_invalid_audio_and_cleans_up(monkeypatch) -> None:
    client = voice_client(monkeypatch)
    temp_paths: list[Path] = []

    class InvalidSTTClient:
        def __init__(self, api_key):
            pass

        def transcribe(self, audio, *args, **kwargs):
            path = Path(audio)
            temp_paths.append(path)
            raise voice.InvalidAudioError("invalid audio data")

    monkeypatch.setattr(voice, "GnaniSTTClient", InvalidSTTClient)
    response = client.post(
        "/voice/stt",
        data={"language_code": "en-IN"},
        files={"audio": ("recording.wav", b"not a wav", "audio/wav")},
    )

    assert response.status_code == 400
    assert "invalid audio data" not in response.text
    assert temp_paths and all(not path.exists() for path in temp_paths)


def test_stt_rejects_unsupported_language_and_format(monkeypatch) -> None:
    client = voice_client(monkeypatch)
    unsupported_language = client.post(
        "/voice/stt",
        data={"language_code": "as-IN"},
        files={"audio": ("recording.wav", b"audio", "audio/wav")},
    )
    unsupported_format = client.post(
        "/voice/stt",
        data={"language_code": "en-IN"},
        files={"audio": ("recording.webm", b"audio", "audio/webm")},
    )

    assert unsupported_language.status_code == 422
    assert unsupported_format.status_code == 415


def test_stt_rejects_oversized_audio(monkeypatch) -> None:
    response = voice_client(monkeypatch).post(
        "/voice/stt",
        data={"language_code": "en-IN"},
        files={"audio": ("recording.wav", b"x" * (voice.MAX_AUDIO_BYTES + 1), "audio/wav")},
    )

    assert response.status_code == 413


def test_stt_missing_key_and_provider_failure_are_safe(monkeypatch) -> None:
    client = voice_client(monkeypatch)
    monkeypatch.setattr(voice.settings, "GNANI_API_KEY", "")
    missing_key = client.post(
        "/voice/stt",
        data={"language_code": "en-IN"},
        files={"audio": ("recording.wav", b"audio", "audio/wav")},
    )
    monkeypatch.setattr(voice.settings, "GNANI_API_KEY", "test-api-key")

    class FailedSTTClient:
        def __init__(self, api_key):
            pass

        def transcribe(self, *args, **kwargs):
            raise requests.ConnectionError("sensitive provider details")

    monkeypatch.setattr(voice, "GnaniSTTClient", FailedSTTClient)
    failed_provider = client.post(
        "/voice/stt",
        data={"language_code": "en-IN"},
        files={"audio": ("recording.wav", b"audio", "audio/wav")},
    )

    assert missing_key.status_code == 503
    assert failed_provider.status_code == 502
    assert "sensitive provider details" not in failed_provider.text


@pytest.mark.parametrize("language_code", ["en-IN", "hi-IN", "ta-IN"])
def test_tts_returns_wav_audio(monkeypatch, language_code) -> None:
    client = voice_client(monkeypatch)
    wav_data = (
        b"RIFF"
        + (38).to_bytes(4, "little")
        + b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + (1).to_bytes(2, "little")
        + (1).to_bytes(2, "little")
        + (48000).to_bytes(4, "little")
        + (96000).to_bytes(4, "little")
        + (2).to_bytes(2, "little")
        + (16).to_bytes(2, "little")
        + b"data"
        + (2).to_bytes(4, "little")
        + b"\x00\x00"
    )
    calls = []

    class FakeTTSClient:
        def __init__(self, api_key):
            assert api_key == "test-api-key"

        @staticmethod
        def supported_voices(model):
            return ["Vasudha"]

        def synthesize(self, text, voice_id, **kwargs):
            calls.append((text, voice_id, kwargs))
            return wav_data

    monkeypatch.setattr(voice, "GnaniTTSClient", FakeTTSClient)
    response = client.post(
        "/voice/tts",
        json={"text": "sample speech", "language_code": language_code},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/wav"
    assert response.headers["cache-control"] == "no-store"
    assert response.content == wav_data
    assert calls[0][0:2] == ("sample speech", "Vasudha")
    assert calls[0][2]["model"] == voice.TTS_MODEL
    assert calls[0][2]["language"] == language_code


@pytest.mark.parametrize("unknown_size", [0x7FFFFFFF, 0xFFFFFFFE, 0xFFFFFFFF])
def test_tts_normalizes_gnani_streaming_wav_sizes(monkeypatch, unknown_size) -> None:
    client = voice_client(monkeypatch)
    sample_data = b"\x10\x00\x20\x00"
    wav_data = (
        b"RIFF"
        + unknown_size.to_bytes(4, "little")
        + b"WAVEfmt "
        + (16).to_bytes(4, "little")
        + (1).to_bytes(2, "little")
        + (1).to_bytes(2, "little")
        + (48000).to_bytes(4, "little")
        + (96000).to_bytes(4, "little")
        + (2).to_bytes(2, "little")
        + (16).to_bytes(2, "little")
        + b"data"
        + unknown_size.to_bytes(4, "little")
        + sample_data
    )

    class StreamingTTSClient:
        def __init__(self, api_key):
            pass

        @staticmethod
        def supported_voices(model):
            return ["Vasudha"]

        def synthesize(self, *args, **kwargs):
            return wav_data

    monkeypatch.setattr(voice, "GnaniTTSClient", StreamingTTSClient)
    response = client.post(
        "/voice/tts",
        json={"text": "hello", "language_code": "en-IN"},
    )

    assert response.status_code == 200
    assert int.from_bytes(response.content[4:8], "little") == len(response.content) - 8
    assert int.from_bytes(response.content[40:44], "little") == len(sample_data)
    with wave.open(io.BytesIO(response.content), "rb") as wav:
        assert wav.getnframes() == 2
        assert wav.readframes(2) == sample_data


def test_tts_rejects_empty_and_unsupported_language(monkeypatch) -> None:
    client = voice_client(monkeypatch)
    empty = client.post("/voice/tts", json={"text": "   ", "language_code": "en-IN"})
    unsupported = client.post("/voice/tts", json={"text": "hello", "language_code": "as-IN"})

    assert empty.status_code == 422
    assert unsupported.status_code == 422


def test_tts_provider_failure_does_not_expose_provider_details(monkeypatch) -> None:
    client = voice_client(monkeypatch)

    class FailedTTSClient:
        def __init__(self, api_key):
            pass

        @staticmethod
        def supported_voices(model):
            return ["Vasudha"]

        def synthesize(self, *args, **kwargs):
            raise requests.ConnectionError("sensitive provider details")

    monkeypatch.setattr(voice, "GnaniTTSClient", FailedTTSClient)
    response = client.post(
        "/voice/tts",
        json={"text": "hello", "language_code": "en-IN"},
    )

    assert response.status_code == 502
    assert "sensitive provider details" not in response.text


def test_tts_rejects_malformed_provider_audio(monkeypatch) -> None:
    client = voice_client(monkeypatch)

    class MalformedTTSClient:
        def __init__(self, api_key):
            pass

        @staticmethod
        def supported_voices(model):
            return ["Vasudha"]

        def synthesize(self, *args, **kwargs):
            return b"not a wav file"

    monkeypatch.setattr(voice, "GnaniTTSClient", MalformedTTSClient)
    response = client.post(
        "/voice/tts",
        json={"text": "hello", "language_code": "en-IN"},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "Gnani returned invalid speech audio."


def test_tts_missing_key_is_reported(monkeypatch) -> None:
    client = voice_client(monkeypatch)
    monkeypatch.setattr(voice.settings, "GNANI_API_KEY", "")

    response = client.post(
        "/voice/tts",
        json={"text": "hello", "language_code": "en-IN"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Gnani voice services are not configured."


def test_chat_advisory_supports_malayalam() -> None:
    from app.routers.ops import ChatRequest
    from app.services.advisory_service import LANGS

    request = ChatRequest(
        lat=27.17,
        lon=78.0,
        language="ml",
        message="നമസ്കാരം",
    )

    assert request.language == "ml"
    assert LANGS["ml"] == "Malayalam"
