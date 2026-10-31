"""Gnani speech services used by the voice assistant."""

import io
import logging
import os
import struct
import tempfile
import wave
from pathlib import Path
from typing import Any

import requests
from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from gnani.stt import (
    APIError as GnaniSTTAPIError,
    GnaniSTTClient,
    InvalidAudioError,
    PRISMA_V3_MODEL,
    SUPPORTED_LANGUAGES,
)
from gnani.stt.client import SUPPORTED_EXTENSIONS
from gnani.tts import (
    APIError as GnaniTTSAPIError,
    AudioConfig,
    GnaniTTSClient,
    SUPPORTED_TTS_LANGUAGES,
)
from pydantic import BaseModel, Field

from ..config import settings

router = APIRouter(prefix="/voice", tags=["Voice"])
logger = logging.getLogger(__name__)
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_TTS_TEXT_LENGTH = 6000
UNKNOWN_WAV_SIZES = {0x7FFFFFFF, 0xFFFFFFFE, 0xFFFFFFFF}
TTS_MODEL = "timbre-v3.0"
TTS_VOICE = "Vasudha"
TTS_LANGUAGES = SUPPORTED_TTS_LANGUAGES - {"auto"}


class SpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=MAX_TTS_TEXT_LENGTH)
    language_code: str = Field(min_length=2, max_length=20)


def _normalize_wav_audio(audio: object) -> bytes | None:
    if not isinstance(audio, bytes) or len(audio) < 44 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        return None

    normalized = bytearray(audio)
    riff_size = struct.unpack_from("<I", normalized, 4)[0]
    if riff_size in UNKNOWN_WAV_SIZES:
        struct.pack_into("<I", normalized, 4, len(normalized) - 8)
    elif riff_size != len(normalized) - 8:
        return None

    format_info: tuple[int, int, int] | None = None
    data_size: int | None = None
    chunk_offset = 12
    while chunk_offset + 8 <= len(normalized):
        chunk_id = normalized[chunk_offset:chunk_offset + 4]
        chunk_size = struct.unpack_from("<I", normalized, chunk_offset + 4)[0]
        chunk_data_offset = chunk_offset + 8
        if chunk_size in UNKNOWN_WAV_SIZES:
            if chunk_id != b"data":
                return None
            chunk_size = len(normalized) - chunk_data_offset
            if chunk_size <= 0:
                return None
            struct.pack_into("<I", normalized, chunk_offset + 4, chunk_size)

        chunk_end = chunk_data_offset + chunk_size
        if chunk_end > len(normalized):
            return None
        if chunk_id == b"fmt ":
            if chunk_size < 16:
                return None
            audio_format, channels, sample_rate, _, block_align, bits_per_sample = struct.unpack_from(
                "<HHIIHH", normalized, chunk_data_offset
            )
            if (
                audio_format != 1
                or channels < 1
                or sample_rate < 1
                or bits_per_sample not in (8, 16, 24, 32)
                or block_align != channels * (bits_per_sample // 8)
            ):
                return None
            format_info = (channels, sample_rate, block_align)
        elif chunk_id == b"data":
            if data_size is not None:
                return None
            data_size = chunk_size

        next_chunk = chunk_end + (chunk_size & 1)
        if next_chunk > len(normalized):
            return None
        chunk_offset = next_chunk

    if chunk_offset != len(normalized) or format_info is None or not data_size:
        return None
    channels, sample_rate, block_align = format_info
    if data_size % block_align:
        return None

    try:
        with wave.open(io.BytesIO(normalized), "rb") as wav:
            if (
                wav.getnchannels() != channels
                or wav.getframerate() != sample_rate
                or wav.getnframes() == 0
                or len(wav.readframes(1)) < block_align
            ):
                return None
    except (wave.Error, EOFError):
        return None

    return bytes(normalized)


def _require_api_key() -> str:
    if not settings.GNANI_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Gnani voice services are not configured.",
        )
    return settings.GNANI_API_KEY


@router.get("/capabilities")
def voice_capabilities() -> dict[str, Any]:
    return {
        "stt": {
            "languages": sorted(SUPPORTED_LANGUAGES),
            "model": PRISMA_V3_MODEL,
            "auto_detection": True,
            "auto_detection_code": "indic-auto",
        },
        "tts": {
            "languages": sorted(TTS_LANGUAGES),
            "model": TTS_MODEL,
            "mime_type": "audio/wav",
        },
    }


@router.post("/stt")
async def speech_to_text(
    audio: UploadFile = File(...),
    language_code: str = Form(default="en-IN"),
) -> dict[str, Any]:
    temp_path: str | None = None
    try:
        api_key = _require_api_key()
        if language_code not in SUPPORTED_LANGUAGES and language_code != "indic-auto":
            raise HTTPException(
                status_code=422,
                detail="The requested speech recognition language is not supported.",
            )

        suffix = Path(audio.filename or "").suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise HTTPException(
                status_code=415,
                detail="Unsupported audio format. Upload WAV, MP3, FLAC, OGG, M4A, or AAC audio.",
            )

        audio_bytes = await audio.read(MAX_AUDIO_BYTES + 1)
        if not audio_bytes:
            raise HTTPException(status_code=400, detail="Audio file is empty.")
        if len(audio_bytes) > MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="Audio file exceeds the 10 MB limit.")

        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp_file:
            temp_file.write(audio_bytes)
            temp_path = temp_file.name

        client = GnaniSTTClient(api_key=api_key)
        result = await run_in_threadpool(
            client.transcribe,
            temp_path,
            language_code,
            model=PRISMA_V3_MODEL,
        )
        if not isinstance(result, dict) or result.get("success") is False:
            raise HTTPException(status_code=502, detail="Gnani returned an invalid transcription response.")

        transcript = result.get("transcript")
        if not isinstance(transcript, str):
            raise HTTPException(status_code=502, detail="Gnani returned an invalid transcription response.")

        detected_language = result.get("detected_language_code")
        model = result.get("model")
        request_id = result.get("request_id")
        return {
            "transcript": transcript,
            "language_code": language_code,
            "detected_language_code": (
                detected_language
                if isinstance(detected_language, str) and detected_language in SUPPORTED_LANGUAGES
                else None
            ),
            "model": model if isinstance(model, str) else PRISMA_V3_MODEL,
            "request_id": request_id if isinstance(request_id, str) else None,
            "truncated": result.get("truncated") is True,
        }
    except HTTPException:
        raise
    except InvalidAudioError as exc:
        logger.info("Gnani rejected uploaded audio (%s)", type(exc).__name__)
        raise HTTPException(status_code=400, detail="The uploaded audio could not be decoded.") from None
    except (GnaniSTTAPIError, requests.exceptions.RequestException, OSError, ValueError) as exc:
        logger.warning("Gnani speech recognition failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Speech recognition is temporarily unavailable.") from None
    finally:
        if temp_path:
            try:
                os.remove(temp_path)
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.warning("Unable to remove temporary speech file (%s)", type(exc).__name__)
        await audio.close()


@router.post("/tts")
async def text_to_speech(request: SpeechRequest) -> Response:
    api_key = _require_api_key()
    text = request.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Text to speak must not be empty.")
    if request.language_code not in TTS_LANGUAGES:
        raise HTTPException(
            status_code=422,
            detail="The requested speech playback language is not supported.",
        )
    if TTS_VOICE not in GnaniTTSClient.supported_voices(TTS_MODEL):
        raise HTTPException(status_code=503, detail="No configured Gnani voice is available.")

    client = GnaniTTSClient(api_key=api_key)
    try:
        audio_result = await run_in_threadpool(
            client.synthesize,
            text,
            TTS_VOICE,
            model=TTS_MODEL,
            language=request.language_code,
            audio_config=AudioConfig(container="wav"),
        )
    except (GnaniTTSAPIError, requests.exceptions.RequestException, OSError, ValueError) as exc:
        logger.warning("Gnani speech synthesis failed (%s)", type(exc).__name__)
        raise HTTPException(status_code=502, detail="Speech synthesis is temporarily unavailable.") from None

    audio_bytes = _normalize_wav_audio(audio_result)
    if audio_bytes is None:
        raise HTTPException(status_code=502, detail="Gnani returned invalid speech audio.")

    return Response(
        content=audio_bytes,
        media_type="audio/wav",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )
