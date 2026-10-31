"""Weather data models."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class DailyWeather(BaseModel):
    date: str
    temperature_2m_max: Optional[float] = None
    temperature_2m_min: Optional[float] = None
    precipitation_probability_max: Optional[int] = None
    precipitation_sum: Optional[float] = None
    wind_speed_10m_max: Optional[float] = None


class WeatherData(BaseModel):
    latitude: float
    longitude: float
    timezone: str
    daily: List[DailyWeather] = Field(default_factory=list)
    retrieved_at: Optional[datetime] = None
    source: str = "Open-Meteo"
    error: Optional[str] = None

    @property
    def max_temp(self) -> Optional[float]:
        values = [d.temperature_2m_max for d in self.daily if d.temperature_2m_max is not None]
        return max(values) if values else None

    @property
    def precipitation_total(self) -> Optional[float]:
        values = [d.precipitation_sum for d in self.daily if d.precipitation_sum is not None]
        if not values:
            return None
        return round(sum(values), 2)
