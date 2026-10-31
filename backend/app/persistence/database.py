"""SQLite connection management and schema initialization."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import settings

DatabasePath = str | Path | None

DEFAULT_DATABASE_PATH = settings.DATA_DIR / "climateguard.sqlite3"

_SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS farms (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL CHECK (length(trim(name)) > 0),
        location TEXT NOT NULL CHECK (length(trim(location)) > 0),
        latitude REAL CHECK (latitude IS NULL OR (latitude >= -90 AND latitude <= 90)),
        longitude REAL CHECK (longitude IS NULL OR (longitude >= -180 AND longitude <= 180)),
        crop TEXT,
        area_hectares REAL CHECK (area_hectares IS NULL OR area_hectares > 0),
        variety TEXT,
        growth_stage TEXT,
        sowing_date TEXT,
        soil_type TEXT,
        irrigation_method TEXT,
        farming_preferences TEXT NOT NULL DEFAULT '{}',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS action_plan_items (
        id TEXT PRIMARY KEY,
        farm_id TEXT NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
        title TEXT NOT NULL CHECK (length(trim(title)) > 0),
        description TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'completed', 'postponed', 'skipped')),
        due_date TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        completed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id TEXT PRIMARY KEY,
        farm_id TEXT NOT NULL REFERENCES farms(id) ON DELETE CASCADE,
        alert_type TEXT NOT NULL CHECK (length(trim(alert_type)) > 0),
        title TEXT NOT NULL CHECK (length(trim(title)) > 0),
        message TEXT NOT NULL CHECK (length(trim(message)) > 0),
        dedupe_key TEXT,
        is_read INTEGER NOT NULL DEFAULT 0 CHECK (is_read IN (0, 1)),
        created_at TEXT NOT NULL,
        read_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_action_items_farm_status ON action_plan_items(farm_id, status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_alerts_farm_created ON alerts(farm_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_alerts_dedupe ON alerts(farm_id, dedupe_key, created_at)",
)


def _resolve_path(database_path: DatabasePath = None) -> Path:
    if database_path is None:
        return DEFAULT_DATABASE_PATH
    return Path(database_path).expanduser().resolve()


@contextmanager
def _connect(database_path: DatabasePath = None) -> Iterator[sqlite3.Connection]:
    path = _resolve_path(database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def transaction(database_path: DatabasePath = None) -> Iterator[sqlite3.Connection]:
    """Run a write operation atomically, rolling back if it raises."""
    with _connect(database_path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
        except BaseException:
            connection.rollback()
            raise
        else:
            connection.commit()


def initialize_database(database_path: DatabasePath = None) -> Path:
    """Create the schema if needed and return the resolved database path."""
    path = _resolve_path(database_path)
    with transaction(path) as connection:
        for statement in _SCHEMA:
            connection.execute(statement)
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(farms)")
        }
        migrations = {
            "state": "ALTER TABLE farms ADD COLUMN state TEXT",
            "district": "ALTER TABLE farms ADD COLUMN district TEXT",
            "variety": "ALTER TABLE farms ADD COLUMN variety TEXT",
            "growth_stage": "ALTER TABLE farms ADD COLUMN growth_stage TEXT",
            "sowing_date": "ALTER TABLE farms ADD COLUMN sowing_date TEXT",
            "soil_type": "ALTER TABLE farms ADD COLUMN soil_type TEXT",
            "irrigation_method": "ALTER TABLE farms ADD COLUMN irrigation_method TEXT",
            "farming_preferences": (
                "ALTER TABLE farms ADD COLUMN farming_preferences TEXT NOT NULL DEFAULT '{}'"
            ),
        }
        for column, statement in migrations.items():
            if column not in columns:
                connection.execute(statement)
    return path
