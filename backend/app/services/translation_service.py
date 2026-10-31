"""Sarvam translation for agricultural advisory text."""

from __future__ import annotations

import re
from typing import Final

import httpx
from fastapi.concurrency import run_in_threadpool
from sarvamai import SarvamAI
from sarvamai.core.api_error import ApiError

from app.config import settings

SUPPORTED_LANGUAGES: Final = {
    "en": ("English", "en-IN"),
    "hi": ("Hindi", "hi-IN"),
    "bn": ("Bengali", "bn-IN"),
    "ta": ("Tamil", "ta-IN"),
    "te": ("Telugu", "te-IN"),
    "mr": ("Marathi", "mr-IN"),
    "gu": ("Gujarati", "gu-IN"),
    "kn": ("Kannada", "kn-IN"),
    "ml": ("Malayalam", "ml-IN"),
    "pa": ("Punjabi", "pa-IN"),
    "or": ("Odia", "od-IN"),
    "as": ("Assamese", "as-IN"),
    "ur": ("Urdu", "ur-IN"),
}
MODEL = "sarvam-translate:v1"
MAX_INPUT_CHARS = 2000
_CROP_NAMES: Final = (
    "Sugarcane",
    "Groundnut",
    "Chickpea",
    "Soybean",
    "Mustard",
    "Wheat",
    "Rice",
    "Maize",
    "Cotton",
    "Potato",
    "Tomato",
)
_CROP_PATTERN = "|".join(re.escape(crop) for crop in _CROP_NAMES)
_PROTECTED_PATTERN = re.compile(
    r"\[S\d+\]"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\bET0\b"
    r"|\bKc\b"
    rf"|\b(?:{_CROP_PATTERN})\b"
    r"|(?<!\w)(?:₹\s*)?\d+(?:,\d{3})*(?:\.\d+)?"
    r"(?:\s*(?:%|mm(?:/day)?|cm|km|m|°\s*[CF]|kg|g|ml|l|ha|hectares?|acres?|quintals?))?"
    r"(?:/quintals?)?(?!\w)",
    re.IGNORECASE,
)


class TranslationError(Exception):
    """Translation failed or returned an unusable response."""


class TranslationNotConfigured(TranslationError):
    """The Sarvam API key is not configured."""


class TranslationTimeout(TranslationError):
    """The Sarvam translation request timed out."""


class TranslationInsufficientCredits(TranslationError):
    """Sarvam rejected the request because credits or quota are unavailable."""


class TranslationCredentialsRejected(TranslationError):
    """Sarvam rejected the configured API key."""


def _protect_advisory(text: str) -> tuple[str, dict[str, str]]:
    protected: dict[str, str] = {}

    def replace(match: re.Match[str]) -> str:
        token = f"ZXQCLIMATEGUARD{len(protected):04d}ZXQ"
        protected[token] = match.group(0)
        return token

    return _PROTECTED_PATTERN.sub(replace, text), protected


def _split_text(text: str) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    while len(text) > MAX_INPUT_CHARS:
        boundary = max(
            text.rfind(" ", 0, MAX_INPUT_CHARS),
            text.rfind("\n", 0, MAX_INPUT_CHARS),
        )
        if boundary <= 0:
            raise TranslationError("Advisory text exceeds Sarvam's per-request limit.")
        separator_end = boundary + 1
        while separator_end < len(text) and text[separator_end].isspace():
            separator_end += 1
        chunks.append((text[:boundary], text[boundary:separator_end]))
        text = text[separator_end:]
    if text:
        chunks.append((text, ""))
    return chunks


def _translate_chunk(text: str, target_language_code: str) -> str:
    client = SarvamAI(api_subscription_key=settings.SARVAM_API_KEY, timeout=30)
    response = client.text.translate(
        input=text,
        source_language_code="en-IN",
        target_language_code=target_language_code,
        model=MODEL,
        mode="formal",
        numerals_format="international",
    )
    translated_text = response.translated_text
    if not isinstance(translated_text, str) or not translated_text.strip():
        raise TranslationError("Sarvam returned an empty translation.")
    return translated_text


async def translate_advisory(text: str, target_language: str) -> str:
    language = SUPPORTED_LANGUAGES.get(target_language)
    if language is None:
        raise TranslationError("The selected translation language is unsupported.")
    if target_language == "en":
        return text
    if not text.strip():
        raise TranslationError("Advisory text is empty.")
    if not settings.SARVAM_API_KEY:
        raise TranslationNotConfigured("Sarvam translation is not configured.")

    protected_text, protected_values = _protect_advisory(text)
    if not protected_text.strip():
        return text
    try:
        translated_chunks = []
        for chunk, separator in _split_text(protected_text):
            translated = await run_in_threadpool(
                _translate_chunk,
                chunk,
                language[1],
            )
            translated_chunks.append(translated + separator)
        translated_text = "".join(translated_chunks)
        if translated_text.strip().casefold() == protected_text.strip().casefold():
            raise TranslationError("Sarvam returned the original English advisory.")
    except TranslationError:
        raise
    except ApiError as exc:
        if exc.status_code in (402, 429):
            raise TranslationInsufficientCredits(
                "Sarvam translation credits or quota are unavailable."
            ) from exc
        if exc.status_code in (401, 403):
            raise TranslationCredentialsRejected(
                "Sarvam rejected the configured API key."
            ) from exc
        raise TranslationError("Sarvam translation request failed.") from exc
    except httpx.TimeoutException as exc:
        raise TranslationTimeout("Sarvam translation request timed out.") from exc
    except (httpx.TransportError, ValueError, TypeError, AttributeError) as exc:
        raise TranslationError("Sarvam translation request failed.") from exc

    for token, original in protected_values.items():
        if translated_text.count(token) != 1:
            raise TranslationError(
                "Sarvam translation did not preserve protected advisory details."
            )
        translated_text = translated_text.replace(token, original)
    return translated_text
