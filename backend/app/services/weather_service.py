"""Weather data service using Open-Meteo.

Hardening for shared-IP hosting. Open-Meteo answers HTTP 429 when one IP sends too many requests, and cloud hosts share IPs:
* the cache key uses coordinates rounded to 2 decimals (about 1 km), so nearby map clicks share one entry;
* a 429 is retried only when Retry-After is short enough to wait within the request; otherwise the service honors the
  provider's cooldown before making another request;
* if the live call fails, the last REAL forecast for that spot (up to 24 h old) is returned with its original retrieved_at
  timestamp and a source label that says it is a cached copy. Nothing is invented. With no cached copy the error is raised.
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.config import settings
from app.models.weather import WeatherData
from app.utils.cache import cache
from app.utils.http import provider_timeout

logger = logging.getLogger(__name__)

STALE_TTL_SECONDS = 24 * 3600
DEFAULT_BLOCK_SECONDS = 60
MAX_INLINE_RETRY_AFTER_SECONDS = 3
MAX_ERROR_BODY_LENGTH = 300
_blocked_until = 0.0
_inflight: dict[str, asyncio.Task[WeatherData]] = {}


class RateLimited(Exception):
    """Open-Meteo is rate limiting this server's IP address."""


async def _fetch(latitude: float, longitude: float) -> dict:
    global _blocked_until
    remaining = _blocked_until - time.time()
    if remaining > 0:
        raise RateLimited(f"Open-Meteo is rate limiting this server; not calling it again for {int(remaining) + 1} s")
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max",
        "timezone": "auto",
        "forecast_days": 14,
    }
    last: Exception | None = None
    for attempt in range(2):
        try:
            async with httpx.AsyncClient(timeout=provider_timeout()) as client:
                response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            if response.status_code >= 400:
                body = re.sub(r"[\x00-\x1f\x7f]+", " ", response.text[:MAX_ERROR_BODY_LENGTH])
                logger.warning(
                    "open-meteo/forecast request failed: status=%s body=%s",
                    response.status_code,
                    body[:MAX_ERROR_BODY_LENGTH],
                )
            if response.status_code == 429:
                header = response.headers.get("retry-after", "")
                wait = _retry_after_seconds(header)
                if wait is None:
                    wait = DEFAULT_BLOCK_SECONDS
                _blocked_until = time.time() + max(wait, 1)
                if attempt == 0 and wait <= MAX_INLINE_RETRY_AFTER_SECONDS:
                    await asyncio.sleep(wait)
                    continue
                raise RateLimited("Open-Meteo returned 429 Too Many Requests; request cooldown is active")
            response.raise_for_status()
            payload = response.json()
            _validate_payload(payload)
            return payload
        except RateLimited:
            raise
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            last = exc
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                raise
            if attempt == 0:
                await asyncio.sleep(0.5 * (2**attempt))
        except (ValueError, UnicodeDecodeError) as exc:
            logger.warning("open-meteo/forecast returned invalid JSON (%s)", type(exc).__name__)
            raise ValueError("Open-Meteo returned invalid forecast JSON.") from exc
    assert last is not None
    raise last


def _retry_after_seconds(value: str) -> float | None:
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


def _validate_payload(payload: object) -> None:
    if not isinstance(payload, dict) or not isinstance(payload.get("daily"), dict):
        raise ValueError("Open-Meteo response is missing daily forecast data.")
    daily = payload["daily"]
    dates = daily.get("time")
    if not isinstance(dates, list) or len(dates) < 14 or any(
        not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) for day in dates
    ):
        raise ValueError("Open-Meteo response has an invalid date series.")
    try:
        for day in dates:
            date.fromisoformat(day)
    except ValueError as exc:
        raise ValueError("Open-Meteo response has an invalid date.") from exc
    available = {"temperature_2m_max": False, "precipitation_sum": False}
    for name in (
        "temperature_2m_max",
        "temperature_2m_min",
        "precipitation_probability_max",
        "precipitation_sum",
        "wind_speed_10m_max",
    ):
        values = daily.get(name)
        if not isinstance(values, list) or len(values) != len(dates):
            raise ValueError(f"Open-Meteo response has an invalid {name} series.")
        for value in values:
            if value is not None and (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError(f"Open-Meteo response contains invalid values in {name}.")
            if value is not None and name in available:
                available[name] = True
    if not all(available.values()):
        raise ValueError("Open-Meteo response lacks temperature or precipitation data.")


def _parse(payload: dict, latitude: float, longitude: float) -> WeatherData:
    _validate_payload(payload)
    daily_payload = payload["daily"]
    dates = daily_payload.get("time", [])
    max_temps = daily_payload.get("temperature_2m_max", [])
    min_temps = daily_payload.get("temperature_2m_min", [])
    rain_probs = daily_payload.get("precipitation_probability_max", [])
    rain_sums = daily_payload.get("precipitation_sum", [])
    wind_speeds = daily_payload.get("wind_speed_10m_max", [])
    return WeatherData(
        latitude=payload.get("latitude", latitude),
        longitude=payload.get("longitude", longitude),
        timezone=payload.get("timezone", "UTC"),
        retrieved_at=datetime.now(timezone.utc),
        daily=[
            {
                "date": dates[index] if index < len(dates) else "",
                "temperature_2m_max": max_temps[index] if index < len(max_temps) else None,
                "temperature_2m_min": min_temps[index] if index < len(min_temps) else None,
                "precipitation_probability_max": rain_probs[index] if index < len(rain_probs) else None,
                "precipitation_sum": rain_sums[index] if index < len(rain_sums) else None,
                "wind_speed_10m_max": wind_speeds[index] if index < len(wind_speeds) else None,
            }
            for index in range(max(len(dates), len(max_temps), len(min_temps), len(rain_probs), len(rain_sums), len(wind_speeds)))
        ],
    )


async def _load_weather(lat: float, lon: float, key: str, stale_key: str) -> WeatherData:
    try:
        weather = _parse(await _fetch(lat, lon), lat, lon)
    except (RateLimited, httpx.TransportError, httpx.HTTPStatusError, ValueError):
        old = cache.get(stale_key)
        if old:
            weather = WeatherData(**old)
            if weather.retrieved_at:
                weather.source = "Open-Meteo (cached copy; the live request failed)"
                return weather
        raise
    dump = weather.model_dump(mode="json")
    cache.set(key, dump, ttl_seconds=settings.CACHE_TTL)
    cache.set(stale_key, dump, ttl_seconds=STALE_TTL_SECONDS)
    return weather


async def get_weather(latitude: float, longitude: float) -> WeatherData:
    lat, lon = round(latitude, 2), round(longitude, 2)
    key, stale_key = f"weather:{lat}:{lon}", f"weather-stale:{lat}:{lon}"
    cached = cache.get(key)
    if cached:
        cached_weather = WeatherData(**cached)
        if cached_weather.retrieved_at:
            return cached_weather
        cache.delete(key)

    task = _inflight.get(key)
    if task is None:
        task = asyncio.create_task(_load_weather(lat, lon, key, stale_key))
        _inflight[key] = task

        def finish(completed: asyncio.Task[WeatherData]) -> None:
            if _inflight.get(key) is completed:
                _inflight.pop(key, None)

        task.add_done_callback(finish)
    return await asyncio.shield(task)
