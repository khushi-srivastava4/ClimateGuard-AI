"""Weather data service using Open-Meteo.

Hardening for shared-IP hosting. Open-Meteo answers HTTP 429 when one IP sends too many requests, and cloud hosts share IPs:
* the cache key uses coordinates rounded to 2 decimals (about 1 km), so nearby map clicks share one entry;
* a 429 is never retried blindly: the service remembers a short "do not call" window (honouring Retry-After);
* if the live call fails, the last REAL forecast for that spot (up to 24 h old) is returned with its original retrieved_at
  timestamp and a source label that says it is a cached copy. Nothing is invented. With no cached copy the error is raised.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.models.weather import WeatherData
from app.utils.cache import cache
from app.utils.http import provider_timeout

STALE_TTL_SECONDS = 24 * 3600
DEFAULT_BLOCK_SECONDS = 60
MAX_BLOCK_SECONDS = 300
_blocked_until = 0.0


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
    for attempt in range(2):                       # a second try only for network trouble or 5xx, never for 429
        try:
            async with httpx.AsyncClient(timeout=provider_timeout()) as client:
                response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
            if response.status_code == 429:
                header = response.headers.get("retry-after", "")
                wait = float(header) if header.replace(".", "", 1).isdigit() else DEFAULT_BLOCK_SECONDS
                _blocked_until = time.time() + min(max(wait, 30), MAX_BLOCK_SECONDS)
                raise RateLimited("Open-Meteo returned 429 Too Many Requests for this server's IP address")
            response.raise_for_status()
            return response.json()
        except RateLimited:
            raise
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            last = exc
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                raise
            if attempt == 0:
                await asyncio.sleep(0.5)
    assert last is not None
    raise last


def _parse(payload: dict, latitude: float, longitude: float) -> WeatherData:
    daily_payload = payload.get("daily", {}) if isinstance(payload.get("daily"), dict) else {}
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


async def get_weather(latitude: float, longitude: float) -> WeatherData:
    lat, lon = round(latitude, 2), round(longitude, 2)      # ~1 km: nearby clicks share one cache entry
    key, stale_key = f"weather:{lat}:{lon}", f"weather-stale:{lat}:{lon}"
    cached = cache.get(key)
    if cached:
        cached_weather = WeatherData(**cached)
        if cached_weather.retrieved_at:
            return cached_weather
        cache.delete(key)

    try:
        weather = _parse(await _fetch(lat, lon), lat, lon)
    except Exception:
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
