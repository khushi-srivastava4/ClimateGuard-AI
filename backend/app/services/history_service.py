"""Historical weather retrieval from Open-Meteo's archive API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings


class HistoryProviderError(RuntimeError):
    """A provider failure with a safe message suitable for an API response."""

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


async def get_weather_history(
    latitude: float, longitude: float, *, days: int = 30
) -> dict[str, Any]:
    """Return observed/reanalysis archive values; no values are synthesized."""
    end_date = (datetime.now(timezone.utc).date() - timedelta(days=1))
    start_date = end_date - timedelta(days=days - 1)
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "daily": (
            "temperature_2m_max,temperature_2m_min,precipitation_sum,"
            "precipitation_hours,wind_speed_10m_max"
        ),
        "timezone": "auto",
    }
    timeout = httpx.Timeout(
        connect=10.0,
        read=settings.HTTP_TIMEOUT,
        write=10.0,
        pool=5.0,
    )
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                "https://archive-api.open-meteo.com/v1/archive",
                params=params,
            )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as error:
        raise HistoryProviderError(
            "Open-Meteo archive rejected the history request.",
            status_code=error.response.status_code,
        ) from error
    except (httpx.RequestError, ValueError) as error:
        raise HistoryProviderError(
            f"Open-Meteo archive request failed ({type(error).__name__})."
        ) from error

    daily = payload.get("daily") if isinstance(payload, dict) else None
    dates = daily.get("time") if isinstance(daily, dict) else None
    if not isinstance(dates, list):
        raise HistoryProviderError("Open-Meteo archive returned an invalid response.")

    values = {
        key: daily.get(key, [])
        for key in (
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_sum",
            "precipitation_hours",
            "wind_speed_10m_max",
        )
    }
    records = [
        {
            "date": day,
            **{
                key: series[index] if isinstance(series, list) and index < len(series) else None
                for key, series in values.items()
            },
        }
        for index, day in enumerate(dates)
        if isinstance(day, str)
    ]
    return {
        "status": "available",
        "source": "Open-Meteo archive",
        "data_kind": "historical reanalysis",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "timezone": payload.get("timezone", "UTC"),
        "daily": records,
    }
