"""TTL SQLite cache utilities."""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional


class SQLiteCache:
    """Small SQLite-backed cache for API responses."""

    def __init__(self, db_path: str = "cache.db", ttl_seconds: int = 3600) -> None:
        self.db_path = Path(db_path)
        self.ttl_seconds = ttl_seconds
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at REAL NOT NULL
                )
                """
            )
            connection.commit()

    def _now(self) -> float:
        return time.time()

    def get(self, key: str) -> Optional[Any]:
        with sqlite3.connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?",
                (key,),
            ).fetchone()
        if not row:
            return None
        value, expires_at = row
        if expires_at < self._now():
            self.delete(key)
            return None
        return json.loads(value)

    def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        expires_at = self._now() + (ttl_seconds if ttl_seconds is not None else self.ttl_seconds)
        payload = json.dumps(value, default=str)
        with sqlite3.connect(self.db_path) as connection:
            connection.execute(
                "INSERT INTO cache(key, value, expires_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, expires_at = excluded.expires_at",
                (key, payload, expires_at),
            )
            connection.commit()

    def delete(self, key: str) -> None:
        with sqlite3.connect(self.db_path) as connection:
            connection.execute("DELETE FROM cache WHERE key = ?", (key,))
            connection.commit()


cache = SQLiteCache(db_path="./cache.db", ttl_seconds=3600)
