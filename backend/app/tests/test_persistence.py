"""Tests for local SQLite persistence services."""

from __future__ import annotations

import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from app.persistence import (
    ActionStatus,
    FarmUpdate,
    InvalidTransitionError,
    NotFoundError,
    PersistenceValidationError,
    create_action_item,
    create_alert,
    create_farm,
    delete_action_item,
    delete_farm,
    get_action_item,
    get_alert,
    get_farm,
    list_action_items,
    list_alerts,
    list_farms,
    mark_alert_read,
    update_action_status,
    update_farm,
)


class PersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_dir.name) / "climateguard.sqlite3"
        self.farm = create_farm(
            "North Field",
            "Punjab",
            latitude=30.7,
            longitude=76.8,
            crop="wheat",
            area_hectares=2.5,
            variety="local",
            growth_stage="vegetative",
            sowing_date="2026-10-01",
            soil_type="loam",
            irrigation_method="drip",
            farming_preferences={"risk_alerts": {"enabled": False, "threshold": 80}},
            database_path=self.database_path,
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_farm_crud_and_validation(self) -> None:
        self.assertEqual(get_farm(self.farm.id, database_path=self.database_path), self.farm)
        self.assertEqual(list_farms(database_path=self.database_path), [self.farm])

        updated = update_farm(
            self.farm.id,
            FarmUpdate(name="  South Field ", crop=None, area_hectares=3),
            database_path=self.database_path,
        )
        self.assertEqual(updated.name, "South Field")
        self.assertIsNone(updated.crop)
        self.assertEqual(updated.area_hectares, 3.0)
        self.assertEqual(updated.location, "Punjab")

        with self.assertRaises(PersistenceValidationError):
            create_farm("", "Punjab", database_path=self.database_path)
        with self.assertRaises(PersistenceValidationError):
            create_farm("Invalid", "Punjab", latitude=91, database_path=self.database_path)
        with self.assertRaises(PersistenceValidationError):
            update_farm(self.farm.id, FarmUpdate(), database_path=self.database_path)

        delete_farm(self.farm.id, database_path=self.database_path)
        self.assertEqual(list_farms(database_path=self.database_path), [])
        with self.assertRaises(NotFoundError):
            get_farm(self.farm.id, database_path=self.database_path)

    def test_existing_farm_schema_is_migrated_and_preferences_round_trip(self) -> None:
        import sqlite3

        legacy_path = Path(self.temp_dir.name) / "legacy.sqlite3"
        connection = sqlite3.connect(legacy_path)
        try:
            connection.execute(
                """
                CREATE TABLE farms (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, location TEXT NOT NULL,
                    latitude REAL, longitude REAL, crop TEXT, area_hectares REAL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
                """
            )
            connection.commit()
        finally:
            connection.close()
        migrated = create_farm(
            "Legacy-compatible farm",
            "Punjab",
            farming_preferences={"risk_alerts": {"threshold": 75}},
            database_path=legacy_path,
        )
        self.assertEqual(migrated.farming_preferences["risk_alerts"]["threshold"], 75)
        self.assertIsNone(migrated.variety)

    def test_farm_delete_cascades_action_items_and_alerts(self) -> None:
        item = create_action_item(
            self.farm.id, "Inspect irrigation", database_path=self.database_path
        )
        alert = create_alert(
            self.farm.id,
            "weather",
            "Heavy rain",
            "Rain is expected.",
            database_path=self.database_path,
        )
        delete_farm(self.farm.id, database_path=self.database_path)
        self.assertEqual(list_action_items(database_path=self.database_path), [])
        self.assertEqual(list_alerts(database_path=self.database_path), [])
        with self.assertRaises(NotFoundError):
            get_action_item(item.id, database_path=self.database_path)
        with self.assertRaises(NotFoundError):
            get_alert(alert.id, database_path=self.database_path)

    def test_action_status_transitions_persist_and_filter(self) -> None:
        item = create_action_item(
            self.farm.id,
            "Check soil moisture",
            description="Use a soil probe",
            due_date=date(2026, 11, 2),
            database_path=self.database_path,
        )
        self.assertEqual(item.status, ActionStatus.PENDING)
        self.assertEqual(item.due_date, "2026-11-02")

        postponed = update_action_status(
            item.id, ActionStatus.POSTPONED, database_path=self.database_path
        )
        pending = update_action_status(
            item.id, ActionStatus.PENDING, database_path=self.database_path
        )
        completed = update_action_status(
            item.id, ActionStatus.COMPLETED, database_path=self.database_path
        )
        self.assertIsNotNone(completed.completed_at)
        self.assertEqual(get_action_item(item.id, database_path=self.database_path), completed)
        self.assertEqual(
            list_action_items(
                self.farm.id,
                status="completed",
                database_path=self.database_path,
            ),
            [completed],
        )
        self.assertEqual(postponed.status, ActionStatus.POSTPONED)
        self.assertEqual(pending.status, ActionStatus.PENDING)
        with self.assertRaises(InvalidTransitionError):
            update_action_status(
                item.id, ActionStatus.SKIPPED, database_path=self.database_path
            )
        with self.assertRaises(PersistenceValidationError):
            create_action_item(self.farm.id, "Bad date", due_date="2026-99-99", database_path=self.database_path)

        delete_action_item(item.id, database_path=self.database_path)
        self.assertEqual(list_action_items(database_path=self.database_path), [])

    def test_alert_deduplication_read_state_and_persistence(self) -> None:
        now = datetime(2026, 10, 31, 0, 0, tzinfo=timezone.utc)
        first = create_alert(
            self.farm.id,
            "weather",
            "Rain warning",
            "Heavy rain expected.",
            dedupe_key="rain:2026-10-31",
            cooldown=timedelta(minutes=30),
            now=now,
            database_path=self.database_path,
        )
        duplicate = create_alert(
            self.farm.id,
            "weather",
            "Updated title",
            "Duplicate warning.",
            dedupe_key="rain:2026-10-31",
            cooldown=timedelta(minutes=30),
            now=now + timedelta(minutes=10),
            database_path=self.database_path,
        )
        self.assertEqual(first.id, duplicate.id)
        self.assertEqual(len(list_alerts(database_path=self.database_path)), 1)

        read = mark_alert_read(first.id, database_path=self.database_path)
        self.assertTrue(read.is_read)
        self.assertIsNotNone(read.read_at)
        self.assertEqual(list_alerts(self.farm.id, unread_only=True, database_path=self.database_path), [])
        unread = mark_alert_read(first.id, False, database_path=self.database_path)
        self.assertFalse(unread.is_read)
        self.assertIsNone(unread.read_at)
        self.assertEqual(get_alert(first.id, database_path=self.database_path), unread)
        self.assertEqual(list_alerts(self.farm.id, unread_only=True, database_path=self.database_path), [unread])

        after_cooldown = create_alert(
            self.farm.id,
            "weather",
            "Rain warning",
            "Still raining.",
            dedupe_key="rain:2026-10-31",
            cooldown=timedelta(minutes=30),
            now=now + timedelta(minutes=31),
            database_path=self.database_path,
        )
        self.assertNotEqual(first.id, after_cooldown.id)
        with self.assertRaises(PersistenceValidationError):
            create_alert(
                self.farm.id,
                "weather",
                "Invalid",
                "Bad cooldown.",
                cooldown=timedelta(seconds=-1),
                database_path=self.database_path,
            )

    def test_records_are_scoped_to_existing_farms(self) -> None:
        with self.assertRaises(NotFoundError):
            create_action_item(
                "missing-farm", "Inspect", database_path=self.database_path
            )
        with self.assertRaises(NotFoundError):
            create_alert(
                "missing-farm",
                "weather",
                "Alert",
                "Message",
                database_path=self.database_path,
            )


if __name__ == "__main__":
    unittest.main()
