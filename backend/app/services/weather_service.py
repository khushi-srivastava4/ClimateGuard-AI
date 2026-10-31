"""Weather data service using Open-Meteo."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from app.config import settings
from app.models.weather import WeatherData
from app.utils.cache import cache
from app.utils.http import provider_timeout
from app.utils.retry import async_retry


@async_retry(retries=1, backoff=0.5)
async def get_weather(latitude: float, longitude: float) -> WeatherData:
    key = f"weather:{latitude}:{longitude}"
    cached = cache.get(key)
    if cached:
        cached_weather = WeatherData(**cached)
        if cached_weather.retrieved_at:
            return cached_weather
        cache.delete(key)

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max",
        "timezone": "auto",
        "forecast_days": 14,
    }
    async with httpx.AsyncClient(timeout=provider_timeout()) as client:
        response = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
        response.raise_for_status()
        payload = response.json()

    daily_payload = payload.get("daily", {}) if isinstance(payload.get("daily"), dict) else {}
    dates = daily_payload.get("time", [])
    max_temps = daily_payload.get("temperature_2m_max", [])
    min_temps = daily_payload.get("temperature_2m_min", [])
    rain_probs = daily_payload.get("precipitation_probability_max", [])
    rain_sums = daily_payload.get("precipitation_sum", [])
    wind_speeds = daily_payload.get("wind_speed_10m_max", [])

    weather = WeatherData(
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
    cache.set(key, weather.model_dump(mode="json"), ttl_seconds=settings.CACHE_TTL)
    return weather
