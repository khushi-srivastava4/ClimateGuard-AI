"""Typed persistence records and validation errors."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Final


class PersistenceValidationError(ValueError):
    """Raised when a persistence operation receives invalid domain data."""


class NotFoundError(LookupError):
    """Raised when a requested local record does not exist."""


class InvalidTransitionError(ValueError):
    """Raised when an action item cannot move to the requested status."""


class ActionStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    POSTPONED = "postponed"
    SKIPPED = "skipped"


class _Unset:
    __slots__ = ()


UNSET: Final = _Unset()


@dataclass(frozen=True)
class Farm:
    id: str
    name: str
    location: str
    state: str | None
    district: str | None
    latitude: float | None
    longitude: float | None
    crop: str | None
    area_hectares: float | None
    variety: str | None
    growth_stage: str | None
    sowing_date: str | None
    soil_type: str | None
    irrigation_method: str | None
    farming_preferences: dict[str, Any]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class FarmUpdate:
    """A partial farm update; use ``None`` to clear optional values."""

    name: str | _Unset = UNSET
    location: str | _Unset = UNSET
    state: str | None | _Unset = UNSET
    district: str | None | _Unset = UNSET
    latitude: float | None | _Unset = UNSET
    longitude: float | None | _Unset = UNSET
    crop: str | None | _Unset = UNSET
    area_hectares: float | None | _Unset = UNSET
    variety: str | None | _Unset = UNSET
    growth_stage: str | None | _Unset = UNSET
    sowing_date: str | None | _Unset = UNSET
    soil_type: str | None | _Unset = UNSET
    irrigation_method: str | None | _Unset = UNSET
    farming_preferences: dict[str, Any] | _Unset = UNSET


@dataclass(frozen=True)
class ActionPlanItem:
    id: str
    farm_id: str
    title: str
    description: str
    status: ActionStatus
    due_date: str | None
    created_at: str
    updated_at: str
    completed_at: str | None


@dataclass(frozen=True)
class AlertRecord:
    id: str
    farm_id: str
    alert_type: str
    title: str
    message: str
    dedupe_key: str | None
    is_read: bool
    created_at: str
    read_at: str | None
