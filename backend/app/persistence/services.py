"""Typed service functions for persistent farm, action, and alert data."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import date, datetime, timedelta, timezone
from math import isfinite
from typing import TypeVar

from .database import DatabasePath, _connect, initialize_database, transaction
from .models import (
    UNSET,
    ActionPlanItem,
    ActionStatus,
    AlertRecord,
    Farm,
    FarmUpdate,
    InvalidTransitionError,
    NotFoundError,
    PersistenceValidationError,
)

T = TypeVar("T")

_ALLOWED_TRANSITIONS: dict[ActionStatus, set[ActionStatus]] = {
    ActionStatus.PENDING: {
        ActionStatus.COMPLETED,
        ActionStatus.POSTPONED,
        ActionStatus.SKIPPED,
    },
    ActionStatus.POSTPONED: {
        ActionStatus.PENDING,
        ActionStatus.COMPLETED,
        ActionStatus.SKIPPED,
    },
    ActionStatus.COMPLETED: set(),
    ActionStatus.SKIPPED: set(),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    moment = _now() if value is None else value
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise PersistenceValidationError("timestamps must include a timezone")
    return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _required_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PersistenceValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _optional_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise PersistenceValidationError(f"{field} must be a string or None")
    cleaned = value.strip()
    return cleaned or None


def _optional_number(
    value: float | int | None, field: str, minimum: float, maximum: float | None = None
) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PersistenceValidationError(f"{field} must be a number or None")
    number = float(value)
    if not isfinite(number):
        raise PersistenceValidationError(f"{field} must be finite")
    if number < minimum or (maximum is not None and number > maximum):
        bounds = f"{minimum} to {maximum}" if maximum is not None else f"greater than {minimum}"
        raise PersistenceValidationError(f"{field} must be {bounds}")
    return number


def _due_date(value: str | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        raise PersistenceValidationError("due_date must be a date, not a datetime")
    if isinstance(value, date):
        return value.isoformat()
    if not isinstance(value, str):
        raise PersistenceValidationError("due_date must be an ISO date string, date, or None")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise PersistenceValidationError("due_date must be a valid ISO date") from error


def _record(factory: type[T], row: sqlite3.Row) -> T:
    values = dict(row)
    if factory is Farm:
        try:
            values["farming_preferences"] = json.loads(values["farming_preferences"])
        except (TypeError, json.JSONDecodeError) as error:
            raise PersistenceValidationError(
                "stored farming preferences are invalid"
            ) from error
    elif factory is ActionPlanItem:
        values["status"] = ActionStatus(values["status"])
    elif factory is AlertRecord:
        values["is_read"] = bool(values["is_read"])
    return factory(**values)


def _require_farm(connection: sqlite3.Connection, farm_id: str) -> None:
    if connection.execute("SELECT 1 FROM farms WHERE id = ?", (farm_id,)).fetchone() is None:
        raise NotFoundError(f"farm not found: {farm_id}")


def create_farm(
    name: str,
    location: str,
    *,
    state: str | None = None,
    district: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    crop: str | None = None,
    area_hectares: float | None = None,
    variety: str | None = None,
    growth_stage: str | None = None,
    sowing_date: str | None = None,
    soil_type: str | None = None,
    irrigation_method: str | None = None,
    farming_preferences: dict[str, object] | None = None,
    database_path: DatabasePath = None,
) -> Farm:
    name = _required_text(name, "name")
    location = _required_text(location, "location")
    state = _optional_text(state, "state")
    district = _optional_text(district, "district")
    latitude = _optional_number(latitude, "latitude", -90, 90)
    longitude = _optional_number(longitude, "longitude", -180, 180)
    crop = _optional_text(crop, "crop")
    area_hectares = _optional_number(area_hectares, "area_hectares", 0)
    if area_hectares is not None and area_hectares <= 0:
        raise PersistenceValidationError("area_hectares must be greater than 0")
    variety = _optional_text(variety, "variety")
    growth_stage = _optional_text(growth_stage, "growth_stage")
    sowing_date = _due_date(sowing_date)
    soil_type = _optional_text(soil_type, "soil_type")
    irrigation_method = _optional_text(irrigation_method, "irrigation_method")
    if farming_preferences is None:
        farming_preferences = {}
    if not isinstance(farming_preferences, dict):
        raise PersistenceValidationError("farming_preferences must be an object")
    try:
        preferences_json = json.dumps(farming_preferences, allow_nan=False)
    except (TypeError, ValueError) as error:
        raise PersistenceValidationError(
            "farming_preferences must contain JSON-compatible values"
        ) from error
    initialize_database(database_path)
    farm_id = str(uuid.uuid4())
    created_at = _timestamp()
    with transaction(database_path) as connection:
        connection.execute(
            """
            INSERT INTO farms
                (id, name, location, state, district, latitude, longitude, crop, area_hectares,
                 variety, growth_stage, sowing_date, soil_type, irrigation_method,
                 farming_preferences, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                farm_id,
                name,
                location,
                state,
                district,
                latitude,
                longitude,
                crop,
                area_hectares,
                variety,
                growth_stage,
                sowing_date,
                soil_type,
                irrigation_method,
                preferences_json,
                created_at,
                created_at,
            ),
        )
        row = connection.execute("SELECT * FROM farms WHERE id = ?", (farm_id,)).fetchone()
    return _record(Farm, row)


def get_farm(farm_id: str, *, database_path: DatabasePath = None) -> Farm:
    initialize_database(database_path)
    with _connect(database_path) as connection:
        row = connection.execute("SELECT * FROM farms WHERE id = ?", (farm_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"farm not found: {farm_id}")
    return _record(Farm, row)


def list_farms(*, database_path: DatabasePath = None) -> list[Farm]:
    initialize_database(database_path)
    with _connect(database_path) as connection:
        rows = connection.execute("SELECT * FROM farms ORDER BY created_at, id").fetchall()
    return [_record(Farm, row) for row in rows]


def update_farm(
    farm_id: str,
    update: FarmUpdate,
    *,
    database_path: DatabasePath = None,
) -> Farm:
    if not isinstance(update, FarmUpdate):
        raise PersistenceValidationError("update must be a FarmUpdate")

    values: dict[str, object] = {}
    normalizers = {
        "name": lambda value: _required_text(value, "name"),
        "location": lambda value: _required_text(value, "location"),
        "state": lambda value: _optional_text(value, "state"),
        "district": lambda value: _optional_text(value, "district"),
        "latitude": lambda value: _optional_number(value, "latitude", -90, 90),
        "longitude": lambda value: _optional_number(value, "longitude", -180, 180),
        "crop": lambda value: _optional_text(value, "crop"),
        "area_hectares": lambda value: _optional_number(value, "area_hectares", 0),
        "variety": lambda value: _optional_text(value, "variety"),
        "growth_stage": lambda value: _optional_text(value, "growth_stage"),
        "sowing_date": _due_date,
        "soil_type": lambda value: _optional_text(value, "soil_type"),
        "irrigation_method": lambda value: _optional_text(value, "irrigation_method"),
    }
    for field, normalize in normalizers.items():
        value = getattr(update, field)
        if value is not UNSET:
            normalized = normalize(value)
            if field == "area_hectares" and normalized is not None and normalized <= 0:
                raise PersistenceValidationError("area_hectares must be greater than 0")
            values[field] = normalized
    if update.farming_preferences is not UNSET:
        if not isinstance(update.farming_preferences, dict):
            raise PersistenceValidationError("farming_preferences must be an object")
        try:
            values["farming_preferences"] = json.dumps(
                update.farming_preferences, allow_nan=False
            )
        except (TypeError, ValueError) as error:
            raise PersistenceValidationError(
                "farming_preferences must contain JSON-compatible values"
            ) from error
    if not values:
        raise PersistenceValidationError("at least one farm field must be provided")

    initialize_database(database_path)
    values["updated_at"] = _timestamp()
    assignments = ", ".join(f"{field} = ?" for field in values)
    with transaction(database_path) as connection:
        cursor = connection.execute(
            f"UPDATE farms SET {assignments} WHERE id = ?",
            (*values.values(), farm_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError(f"farm not found: {farm_id}")
        row = connection.execute("SELECT * FROM farms WHERE id = ?", (farm_id,)).fetchone()
    return _record(Farm, row)


def delete_farm(farm_id: str, *, database_path: DatabasePath = None) -> None:
    initialize_database(database_path)
    with transaction(database_path) as connection:
        cursor = connection.execute("DELETE FROM farms WHERE id = ?", (farm_id,))
        if cursor.rowcount == 0:
            raise NotFoundError(f"farm not found: {farm_id}")


def create_action_item(
    farm_id: str,
    title: str,
    *,
    description: str = "",
    due_date: str | date | None = None,
    database_path: DatabasePath = None,
) -> ActionPlanItem:
    title = _required_text(title, "title")
    if not isinstance(description, str):
        raise PersistenceValidationError("description must be a string")
    description = description.strip()
    due_date_value = _due_date(due_date)
    initialize_database(database_path)
    item_id = str(uuid.uuid4())
    created_at = _timestamp()
    with transaction(database_path) as connection:
        _require_farm(connection, farm_id)
        connection.execute(
            """
            INSERT INTO action_plan_items
                (id, farm_id, title, description, status, due_date, created_at, updated_at, completed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                item_id,
                farm_id,
                title,
                description,
                ActionStatus.PENDING.value,
                due_date_value,
                created_at,
                created_at,
            ),
        )
        row = connection.execute(
            "SELECT * FROM action_plan_items WHERE id = ?", (item_id,)
        ).fetchone()
    return _record(ActionPlanItem, row)


def get_action_item(
    item_id: str, *, database_path: DatabasePath = None
) -> ActionPlanItem:
    initialize_database(database_path)
    with _connect(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM action_plan_items WHERE id = ?", (item_id,)
        ).fetchone()
    if row is None:
        raise NotFoundError(f"action item not found: {item_id}")
    return _record(ActionPlanItem, row)


def list_action_items(
    farm_id: str | None = None,
    *,
    status: ActionStatus | str | None = None,
    database_path: DatabasePath = None,
) -> list[ActionPlanItem]:
    initialize_database(database_path)
    filters: list[str] = []
    parameters: list[object] = []
    if farm_id is not None:
        filters.append("farm_id = ?")
        parameters.append(farm_id)
    if status is not None:
        try:
            parsed_status = ActionStatus(status)
        except ValueError as error:
            raise PersistenceValidationError(f"invalid action status: {status}") from error
        filters.append("status = ?")
        parameters.append(parsed_status.value)
    where_clause = f" WHERE {' AND '.join(filters)}" if filters else ""
    with _connect(database_path) as connection:
        rows = connection.execute(
            f"SELECT * FROM action_plan_items{where_clause} ORDER BY created_at, id",
            parameters,
        ).fetchall()
    return [_record(ActionPlanItem, row) for row in rows]


def update_action_status(
    item_id: str,
    status: ActionStatus | str,
    *,
    database_path: DatabasePath = None,
) -> ActionPlanItem:
    try:
        next_status = ActionStatus(status)
    except ValueError as error:
        raise PersistenceValidationError(f"invalid action status: {status}") from error
    initialize_database(database_path)
    now = _timestamp()
    with transaction(database_path) as connection:
        row = connection.execute(
            "SELECT * FROM action_plan_items WHERE id = ?", (item_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"action item not found: {item_id}")
        current_status = ActionStatus(row["status"])
        if next_status != current_status and next_status not in _ALLOWED_TRANSITIONS[current_status]:
            raise InvalidTransitionError(
                f"cannot change action item from {current_status.value} to {next_status.value}"
            )
        completed_at = row["completed_at"]
        if next_status == ActionStatus.COMPLETED and current_status != next_status:
            completed_at = now
        elif next_status != ActionStatus.COMPLETED:
            completed_at = None
        connection.execute(
            """
            UPDATE action_plan_items
            SET status = ?, updated_at = ?, completed_at = ?
            WHERE id = ?
            """,
            (next_status.value, now, completed_at, item_id),
        )
        updated = connection.execute(
            "SELECT * FROM action_plan_items WHERE id = ?", (item_id,)
        ).fetchone()
    return _record(ActionPlanItem, updated)


def delete_action_item(item_id: str, *, database_path: DatabasePath = None) -> None:
    initialize_database(database_path)
    with transaction(database_path) as connection:
        cursor = connection.execute(
            "DELETE FROM action_plan_items WHERE id = ?", (item_id,)
        )
        if cursor.rowcount == 0:
            raise NotFoundError(f"action item not found: {item_id}")


def create_alert(
    farm_id: str,
    alert_type: str,
    title: str,
    message: str,
    *,
    dedupe_key: str | None = None,
    cooldown: timedelta = timedelta(minutes=30),
    now: datetime | None = None,
    database_path: DatabasePath = None,
) -> AlertRecord:
    alert_type = _required_text(alert_type, "alert_type")
    title = _required_text(title, "title")
    message = _required_text(message, "message")
    dedupe_key = _optional_text(dedupe_key, "dedupe_key")
    if not isinstance(cooldown, timedelta) or cooldown < timedelta(0):
        raise PersistenceValidationError("cooldown must be a non-negative timedelta")
    created_at = _timestamp(now)
    initialize_database(database_path)
    alert_id = str(uuid.uuid4())
    with transaction(database_path) as connection:
        _require_farm(connection, farm_id)
        if dedupe_key is not None and cooldown > timedelta(0):
            cutoff = _timestamp((now or _now()) - cooldown)
            existing = connection.execute(
                """
                SELECT * FROM alerts
                WHERE farm_id = ? AND dedupe_key = ? AND created_at >= ?
                ORDER BY created_at DESC, id DESC
                LIMIT 1
                """,
                (farm_id, dedupe_key, cutoff),
            ).fetchone()
            if existing is not None:
                return _record(AlertRecord, existing)
        connection.execute(
            """
            INSERT INTO alerts
                (id, farm_id, alert_type, title, message, dedupe_key, is_read, created_at, read_at)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, NULL)
            """,
            (alert_id, farm_id, alert_type, title, message, dedupe_key, created_at),
        )
        row = connection.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    return _record(AlertRecord, row)


def get_alert(alert_id: str, *, database_path: DatabasePath = None) -> AlertRecord:
    initialize_database(database_path)
    with _connect(database_path) as connection:
        row = connection.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    if row is None:
        raise NotFoundError(f"alert not found: {alert_id}")
    return _record(AlertRecord, row)


def list_alerts(
    farm_id: str | None = None,
    *,
    unread_only: bool = False,
    database_path: DatabasePath = None,
) -> list[AlertRecord]:
    initialize_database(database_path)
    filters: list[str] = []
    parameters: list[object] = []
    if farm_id is not None:
        filters.append("farm_id = ?")
        parameters.append(farm_id)
    if unread_only:
        filters.append("is_read = 0")
    where_clause = f" WHERE {' AND '.join(filters)}" if filters else ""
    with _connect(database_path) as connection:
        rows = connection.execute(
            f"SELECT * FROM alerts{where_clause} ORDER BY created_at DESC, id",
            parameters,
        ).fetchall()
    return [_record(AlertRecord, row) for row in rows]


def mark_alert_read(
    alert_id: str,
    is_read: bool = True,
    *,
    database_path: DatabasePath = None,
) -> AlertRecord:
    if not isinstance(is_read, bool):
        raise PersistenceValidationError("is_read must be a bool")
    initialize_database(database_path)
    read_at = _timestamp() if is_read else None
    with transaction(database_path) as connection:
        cursor = connection.execute(
            "UPDATE alerts SET is_read = ?, read_at = ? WHERE id = ?",
            (int(is_read), read_at, alert_id),
        )
        if cursor.rowcount == 0:
            raise NotFoundError(f"alert not found: {alert_id}")
        row = connection.execute("SELECT * FROM alerts WHERE id = ?", (alert_id,)).fetchone()
    return _record(AlertRecord, row)
