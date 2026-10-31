"""Risk report models."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class RiskReport(BaseModel):
    heat_wave: Optional[int] = None
    flood: Optional[int] = None
    water_logging: Optional[int] = None
    drought: Optional[int] = None
    overall: Optional[int] = None
    category: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)
    sources: List[str] = Field(default_factory=list)
    data_quality: List[str] = Field(default_factory=list)
    assessment_period: Optional[str] = None
    error: Optional[str] = None

    def to_payload(self) -> dict:
        return {
            "heat_wave": self.heat_wave,
            "flood": self.flood,
            "water_logging": self.water_logging,
            "drought": self.drought,
            "overall": self.overall,
            "category": self.category,
            "reasons": self.reasons,
            "sources": self.sources,
            "data_quality": self.data_quality,
            "assessment_period": self.assessment_period,
            "error": self.error,
        }
