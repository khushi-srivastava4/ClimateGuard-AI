"""Soil property models."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class SoilProperty(BaseModel):
    name: str
    value: Optional[float] = None
    unit: str = ""


class SoilData(BaseModel):
    latitude: float
    longitude: float
    properties: Dict[str, float] = Field(default_factory=dict)
    property_units: Dict[str, str] = Field(default_factory=dict)
    depth: Optional[str] = None
    source: str = "ISRIC SoilGrids"
    error: Optional[str] = None
    retrieved_at: Optional[datetime] = None

    def summary(self) -> List[str]:
        return [f"{key}={value}" for key, value in self.properties.items()]
