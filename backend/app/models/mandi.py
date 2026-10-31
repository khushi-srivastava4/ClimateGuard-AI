"""Mandi pricing models."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class MandiPricePoint(BaseModel):
    date: str
    market: str = ""
    price: Optional[float] = None
    commodity: str = ""
    unit: str = "₹/quintal"


class MandiData(BaseModel):
    crop: str
    market: str = ""
    prices: List[MandiPricePoint] = Field(default_factory=list)
    source: str = "Agmarknet"
    error: Optional[str] = None
    retrieved_at: Optional[datetime] = None

    @property
    def average_price(self) -> Optional[float]:
        if not self.prices:
            return None
        values = [p.price for p in self.prices if p.price is not None]
        return round(sum(values) / len(values), 2) if values else None
