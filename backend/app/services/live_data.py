"""Live data connectors with bounded retries, request coalescing, caching and status."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Callable

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class SourceError(Exception):
    def __init__(self, source: str, msg: str):
        super().__init__(f"{source}: {msg}")
        self.source, self.msg = source, msg


STATUS: dict[str, dict[str, Any]] = {}
_cache: dict[str, tuple[float, Any]] = {}
_inflight: dict[str, asyncio.Task[Any]] = {}
_blocked_until: dict[str, float] = {}
_client: httpx.AsyncClient | None = None

RETRY_BACKOFF_SECONDS = 0.5
MAX_INLINE_RETRY_AFTER_SECONDS = 3.0
MAX_ERROR_BODY_LENGTH = 300
STALE_CACHE_SECONDS = 24 * 60 * 60
MIN_ASSESSMENT_DAYS = 44


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            headers={"User-Agent": settings.HTTP_USER_AGENT},
            follow_redirects=True,
        )
    return _client


def _safe_excerpt(response: httpx.Response, params: dict | None) -> str:
    text = response.text[:MAX_ERROR_BODY_LENGTH]
    for name, value in (params or {}).items():
        if any(term in str(name).lower() for term in ("key", "token", "authorization", "secret")):
            if value:
                text = text.replace(str(value), "[redacted]")
    text = re.sub(
        r"(?i)(\"?(?:api[-_]?key|token|authorization|secret)\"?\s*[:=]\s*\"?)[^,\"'\s}&]+",
        r"\1[redacted]",
        text,
    )
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    return text[:MAX_ERROR_BODY_LENGTH]


def _retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(value)
            if retry_at.tzinfo is None:
                retry_at = retry_at.replace(tzinfo=timezone.utc)
            return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return None


def _connection_error(exc: Exception) -> str:
    if isinstance(exc, httpx.ConnectTimeout):
        return "connection timed out"
    if isinstance(exc, httpx.ReadTimeout):
        return "response timed out"
    if isinstance(exc, httpx.TimeoutException):
        return "request timed out"
    if isinstance(exc, httpx.ConnectError):
        details = [str(exc)]
        pending = [exc.__cause__, exc.__context__]
        seen: set[int] = set()
        while pending:
            cause = pending.pop()
            if cause is None or id(cause) in seen:
                continue
            seen.add(id(cause))
            details.append(str(cause))
            pending.extend((cause.__cause__, cause.__context__))
            pending.extend(getattr(cause, "exceptions", ()))
        detail = " ".join(details).lower()
        if any(term in detail for term in ("getaddrinfo", "name or service not known", "name resolution", "nodename")):
            return "DNS resolution failed"
        if "refused" in detail or "actively refused" in detail:
            return "connection refused"
        return "connection failed"
    if isinstance(exc, httpx.ProxyError):
        return "proxy connection failed"
    return type(exc).__name__


def _error_message(exc: Exception, response: httpx.Response | None = None, params: dict | None = None) -> str:
    if response is not None and response.status_code >= 400:
        return f"HTTP {response.status_code}: {_safe_excerpt(response, params)}".rstrip()
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}: {_safe_excerpt(exc.response, params)}".rstrip()
    if isinstance(exc, json.JSONDecodeError):
        return "invalid JSON response"
    if isinstance(exc, ValueError):
        return f"invalid provider response: {exc}"
    return _connection_error(exc)


def _retryable_status(status: int) -> bool:
    return status == 429 or status >= 500


def _cache_key(
    url: str,
    params: dict | None,
    text: bool,
    validator: Callable[[Any], None] | None,
) -> str:
    normalized = tuple(sorted((str(key), repr(value)) for key, value in (params or {}).items()))
    validator_name = getattr(validator, "__qualname__", "") if validator else ""
    return f"{url}?{normalized!r}|text={text}|validator={validator_name}"


async def _request(
    source: str,
    url: str,
    params: dict | None,
    retries: int,
    timeout: float | httpx.Timeout,
    text: bool,
    validator: Callable[[Any], None] | None,
) -> Any:
    blocked = _blocked_until.get(source, 0.0) - time.time()
    if blocked > 0:
        raise SourceError(source, f"rate limited; retry after approximately {int(blocked) + 1} seconds")

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        started = time.monotonic()
        response: httpx.Response | None = None
        try:
            response = await _http().get(url, params=params, timeout=timeout)
            if response.status_code >= 400:
                error = httpx.HTTPStatusError(
                    f"upstream returned HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
                logger.warning(
                    "%s request failed (attempt %s/%s): status=%s body=%s",
                    source,
                    attempt + 1,
                    retries + 1,
                    response.status_code,
                    _safe_excerpt(response, params),
                )
                last_error = error
                if response.status_code == 429:
                    retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
                    if retry_after is None:
                        retry_after = RETRY_BACKOFF_SECONDS * (2**attempt)
                    _blocked_until[source] = time.time() + retry_after
                    if attempt >= retries:
                        break
                    if retry_after > MAX_INLINE_RETRY_AFTER_SECONDS:
                        break
                    await asyncio.sleep(retry_after)
                    continue
                if not _retryable_status(response.status_code) or attempt >= retries:
                    break
                await asyncio.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
                continue

            data = response.text if text else response.json()
            if validator:
                validator(data)
            STATUS[source] = {
                "state": "live",
                "latency_ms": int((time.monotonic() - started) * 1000),
                "ts": int(time.time()),
            }
            return data
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = exc
            logger.warning(
                "%s request failed (attempt %s/%s): %s",
                source,
                attempt + 1,
                retries + 1,
                _connection_error(exc),
            )
            if attempt >= retries:
                break
            await asyncio.sleep(RETRY_BACKOFF_SECONDS * (2**attempt))
        except (ValueError, UnicodeDecodeError) as exc:
            last_error = exc
            logger.warning("%s returned invalid response data (%s)", source, type(exc).__name__)
            break
        except Exception:
            logger.exception("%s encountered an unexpected response-processing error", source)
            raise

    if last_error is None:
        raise SourceError(source, "request failed without a response")
    message = _error_message(last_error, response, params)
    logger.warning("%s unavailable: %s", source, message)
    raise SourceError(source, message) from last_error


async def fetch(
    source: str,
    url: str,
    params: dict | None = None,
    ttl: int = 600,
    retries: int = 2,
    timeout: float | httpx.Timeout = 15.0,
    text: bool = False,
    *,
    validator: Callable[[Any], None] | None = None,
    stale_if_error: bool = True,
) -> Any:
    """Fetch and cache successful provider data; concurrent identical calls share one request."""
    key = _cache_key(url, params, text, validator)
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]

    task = _inflight.get(key)
    if task is None:
        task = asyncio.create_task(_request(source, url, params, retries, timeout, text, validator))
        _inflight[key] = task

        def finish(completed: asyncio.Task[Any]) -> None:
            if _inflight.get(key) is completed:
                _inflight.pop(key, None)
            if not completed.cancelled():
                completed.exception()

        task.add_done_callback(finish)

    try:
        result = await asyncio.shield(task)
        _cache[key] = (time.time(), result)
        return result
    except SourceError as exc:
        if stale_if_error and hit and now - hit[0] < STALE_CACHE_SECONDS:
            STATUS[source] = {"state": "stale", "error": exc.msg, "ts": int(hit[0])}
            return hit[1]
        STATUS[source] = {"state": "unavailable", "error": exc.msg, "ts": int(time.time())}
        raise


def _validate_forecast(payload: Any) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("daily"), dict):
        raise ValueError("forecast response is missing daily data")
    daily = payload["daily"]
    dates = daily.get("time")
    if not isinstance(dates, list) or len(dates) < MIN_ASSESSMENT_DAYS or any(
        not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) for day in dates
    ):
        raise ValueError("forecast response has an incomplete daily date series")
    try:
        for day in dates:
            date.fromisoformat(day)
    except ValueError as exc:
        raise ValueError("forecast response has an invalid date") from exc
    for name in ("temperature_2m_max", "precipitation_sum", "et0_fao_evapotranspiration"):
        values = daily.get(name)
        if not isinstance(values, list) or len(values) != len(dates):
            raise ValueError(f"forecast response has an invalid {name} series")
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            for value in values
        ):
            raise ValueError(f"forecast response contains invalid values in {name}")


def validate_mandi_payload(payload: Any) -> None:
    if (
        not isinstance(payload, dict)
        or not isinstance(payload.get("records"), list)
        or any(not isinstance(record, dict) for record in payload["records"])
    ):
        raise ValueError("mandi response is missing its records list")


async def forecast(lat: float, lon: float) -> dict:
    return await fetch(
        "open-meteo/forecast",
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": round(lat, 2),
            "longitude": round(lon, 2),
            "timezone": "auto",
            "past_days": 30,
            "forecast_days": 16,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,et0_fao_evapotranspiration,"
            "wind_gusts_10m_max,precipitation_probability_max",
            "hourly": "soil_moisture_0_to_7cm,soil_moisture_7_to_28cm,soil_temperature_6cm",
        },
        ttl=900,
        validator=_validate_forecast,
    )


async def grid_forecast(points: list[tuple[float, float]]) -> list[dict]:
    result = await fetch(
        "open-meteo/forecast",
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": ",".join(f"{a:.3f}" for a, _ in points),
            "longitude": ",".join(f"{b:.3f}" for _, b in points),
            "daily": "temperature_2m_max,precipitation_sum,et0_fao_evapotranspiration",
            "forecast_days": 7,
            "timezone": "auto",
        },
        ttl=900,
    )
    return result if isinstance(result, list) else [result]


async def flood(lat: float, lon: float) -> dict:
    return await fetch(
        "open-meteo/flood",
        "https://flood-api.open-meteo.com/v1/flood",
        {
            "latitude": round(lat, 4),
            "longitude": round(lon, 4),
            "daily": "river_discharge",
            "past_days": 60,
            "forecast_days": 16,
        },
        ttl=3600,
    )


async def climatology(lat: float, lon: float) -> dict:
    payload = await fetch(
        "nasa-power",
        "https://power.larc.nasa.gov/api/temporal/climatology/point",
        {
            "parameters": "PRECTOTCORR,T2M_MAX",
            "community": "AG",
            "longitude": round(lon, 3),
            "latitude": round(lat, 3),
            "format": "JSON",
        },
        ttl=86400 * 30,
        timeout=25,
    )
    parameters = payload["properties"]["parameter"]
    return {
        key: {month: value for month, value in values.items() if value is not None and value > -900}
        for key, values in parameters.items()
    }


async def enso() -> dict:
    text = await fetch(
        "noaa-cpc/oni",
        "https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt",
        ttl=86400,
        text=True,
    )
    rows = [line.split() for line in text.splitlines() if re.match(r"^\s*[A-Z]{3}\s+\d{4}\s", line)]
    if not rows:
        raise SourceError("noaa-cpc/oni", "unexpected file format")
    season, year, _, anomaly = rows[-1][:4]
    value = float(anomaly)
    return {
        "season": f"{season} {year}",
        "oni": value,
        "phase": "El Niño" if value >= 0.5 else "La Niña" if value <= -0.5 else "Neutral",
    }
