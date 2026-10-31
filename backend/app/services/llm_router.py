"""LLM failover router: primary provider from LLM_PROVIDER/LLM_API_KEY/LLM_MODEL, then any backup keys.

A provider that answers 429/5xx is put on cooldown (never hammered), identical prompts are cached for 30 minutes, and the
result always names the provider that really wrote the text.
"""

from __future__ import annotations

import hashlib
import time
from typing import Dict, List, Optional

import httpx
import openai
from openai import AsyncOpenAI

from app.config import settings

COOLDOWN: Dict[str, float] = {}
CACHE: Dict[str, tuple] = {}
CACHE_TTL = 1800
_TIMEOUT = httpx.Timeout(connect=8.0, read=20.0, write=5.0, pool=2.0)


class ProviderError(Exception):
    def __init__(self, msg: str, status: Optional[int] = None, retry_after: Optional[int] = None):
        super().__init__(msg)
        self.status, self.retry_after = status, retry_after


class AllProvidersFailed(Exception):
    def __init__(self, attempts: List[dict]):
        super().__init__("; ".join(f"{a['provider']}: {a.get('error')}" for a in attempts))
        self.attempts = attempts


def providers() -> List[dict]:
    """Configured providers, primary first. Entries without a key are skipped."""
    out = []
    if settings.LLM_API_KEY:
        out.append({"name": settings.LLM_PROVIDER.lower(), "kind": settings.LLM_PROVIDER.upper(),
                    "key": settings.LLM_API_KEY, "model": settings.LLM_MODEL})
    backups = [("openai", "OPENAI", settings.BACKUP_OPENAI_API_KEY, settings.BACKUP_OPENAI_MODEL),
               ("anthropic", "ANTHROPIC", settings.BACKUP_ANTHROPIC_API_KEY, settings.BACKUP_ANTHROPIC_MODEL),
               ("groq", "GROQ", settings.BACKUP_GROQ_API_KEY, settings.BACKUP_GROQ_MODEL),
               ("gemini", "GEMINI", settings.BACKUP_GEMINI_API_KEY, settings.BACKUP_GEMINI_MODEL)]
    for name, kind, key, model in backups:
        if key and not any(p["kind"] == kind and p["key"] == key for p in out):
            out.append({"name": name + "-backup", "kind": kind, "key": key, "model": model})
    return out


def _check(r: httpx.Response) -> None:
    if r.status_code == 429 or r.status_code >= 500:
        ra = r.headers.get("retry-after", "")
        raise ProviderError("HTTP %s (%s)" % (r.status_code, "quota or rate limit" if r.status_code == 429 else "server error"),
                            r.status_code, int(ra) if ra.isdigit() else None)
    if r.status_code >= 400:
        raise ProviderError(f"HTTP {r.status_code}", r.status_code)


async def _call(p: dict, prompt: str, system: str) -> str:
    kind, key, model = p["kind"], p["key"], p["model"]
    async with httpx.AsyncClient(timeout=_TIMEOUT) as c:
        if kind == "GEMINI":
            cfg = {"temperature": 0.2, "maxOutputTokens": 1200}
            if "flash" in model:
                cfg["thinkingConfig"] = {"thinkingBudget": 0}   # thinking tokens otherwise eat the output budget
            r = await c.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                             headers={"x-goog-api-key": key},
                             json={"systemInstruction": {"parts": [{"text": system}]},
                                   "contents": [{"role": "user", "parts": [{"text": prompt}]}], "generationConfig": cfg})
            _check(r)
            cands = r.json().get("candidates") or [{}]
            parts = (cands[0].get("content") or {}).get("parts") or []
            return "".join(x.get("text", "") for x in parts if isinstance(x, dict)).strip()
        if kind == "ANTHROPIC":
            r = await c.post("https://api.anthropic.com/v1/messages",
                             headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                             json={"model": model, "max_tokens": 1000, "temperature": 0.2, "system": system,
                                   "messages": [{"role": "user", "content": prompt}]})
            _check(r)
            return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text").strip()
        if kind == "OPENAI":
            try:
                async with AsyncOpenAI(api_key=key, timeout=_TIMEOUT) as client:
                    response = await client.chat.completions.create(
                        model=model,
                        temperature=0.2,
                        messages=[
                            {"role": "system", "content": system},
                            {"role": "user", "content": prompt},
                        ],
                    )
            except openai.OpenAIError as exc:
                raise _openai_provider_error(exc) from None
            choices = response.choices
            content = choices[0].message.content if choices else None
            return content.strip() if isinstance(content, str) else ""

        url = ("https://api.groq.com/openai/v1/chat/completions" if kind == "GROQ"
               else (settings.LLM_BASE_URL.rstrip("/") + "/chat/completions") if settings.LLM_BASE_URL
               else "https://api.openai.com/v1/chat/completions")
        r = await c.post(url, headers={"Authorization": f"Bearer {key}"},
                         json={"model": model, "temperature": 0.2,
                               "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]})
        _check(r)
        return (((r.json().get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()


def _openai_provider_error(error: openai.OpenAIError) -> ProviderError:
    status = getattr(error, "status_code", None)
    if isinstance(error, openai.RateLimitError):
        error_code = getattr(error, "code", None)
        if not error_code and isinstance(getattr(error, "body", None), dict):
            details = error.body.get("error")
            if isinstance(details, dict):
                error_code = details.get("code")
        message = (
            "insufficient API credits or quota"
            if error_code == "insufficient_quota"
            else "rate limit exceeded"
        )
    elif isinstance(error, openai.AuthenticationError):
        message = "invalid API key"
    elif isinstance(error, openai.PermissionDeniedError):
        message = "API key lacks permission for this request or model"
    elif isinstance(error, openai.NotFoundError):
        message = "model not found or unavailable to this API account"
    elif isinstance(error, openai.APITimeoutError):
        message = "request timed out"
    elif isinstance(error, openai.APIConnectionError):
        message = "connection failed"
    elif status is not None and status >= 500:
        message = "server error"
    elif status is not None:
        message = f"request rejected (HTTP {status})"
    else:
        message = "OpenAI request failed"

    retry_after = None
    response = getattr(error, "response", None)
    if response is not None:
        retry_value = response.headers.get("retry-after", "")
        try:
            retry_after = max(1, int(float(retry_value)))
        except (TypeError, ValueError):
            pass
    return ProviderError(message, status, retry_after)


async def generate(prompt: str, system: str, skip: Optional[List[str]] = None, use_cache: bool = True) -> dict:
    """Try each configured provider (except those named in `skip`). Raises AllProvidersFailed."""
    ck = hashlib.sha256((system + "\x00" + prompt).encode()).hexdigest()
    hit = CACHE.get(ck)
    if use_cache and hit and time.time() - hit[0] < CACHE_TTL:
        return {**hit[1], "cached": True}
    attempts: List[dict] = []
    for p in providers():
        if skip and (p["name"] in skip or p["kind"].lower() in skip):
            continue
        if COOLDOWN.get(p["name"], 0) > time.time():
            attempts.append({"provider": p["name"], "ok": False, "error": f"cooling down after a rate limit ({int(COOLDOWN[p['name']] - time.time())} s left)"})
            continue
        try:
            text = await _call(p, prompt, system)
            if not text:
                raise ProviderError("empty response")
            res = {"text": text, "provider": p["name"], "model": p["model"], "cached": False,
                   "attempts": attempts + [{"provider": p["name"], "ok": True}]}
            CACHE[ck] = (time.time(), res)
            return res
        except ProviderError as e:
            if e.status == 429 or (e.status or 0) >= 500:
                COOLDOWN[p["name"]] = time.time() + (e.retry_after or 120)
            attempts.append({"provider": p["name"], "ok": False, "error": str(e)})
        except (httpx.TimeoutException, httpx.TransportError) as e:
            COOLDOWN[p["name"]] = time.time() + 30
            attempts.append({"provider": p["name"], "ok": False, "error": type(e).__name__})
    if (
        skip
        and "gemini" in skip
        and not settings.BACKUP_OPENAI_API_KEY
        and not any(attempt["provider"] == "openai-backup" for attempt in attempts)
    ):
        attempts.append({
            "provider": "openai-backup",
            "ok": False,
            "error": "OPENAI_API_KEY is not configured",
        })
    if not attempts:
        attempts.append({"provider": "none", "ok": False, "error": "no LLM API key configured"})
    raise AllProvidersFailed(attempts)
