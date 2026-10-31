"""Tiny SQLite document/event store for the operational modules (grid sites, relief suppliers, telemetry, orders...).

Separate file from the farm database on purpose: it cannot disturb your existing persistence layer.
Set OPS_DB to change the location (tests use a temp file).
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, updated REAL NOT NULL, PRIMARY KEY(kind, id));
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, ref TEXT, ts REAL NOT NULL, body TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ev_kind ON events(kind, ref, ts);
"""


def _path() -> Path:
    return Path(os.getenv("OPS_DB") or Path(__file__).resolve().parents[2] / "data" / "ops.sqlite3")


def _conn() -> sqlite3.Connection:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(p, timeout=10)
    c.executescript(SCHEMA)
    return c


def put(kind: str, id: str, obj: Dict[str, Any]) -> Dict[str, Any]:
    with _conn() as c:
        c.execute("INSERT INTO docs(kind,id,body,updated) VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body, updated=excluded.updated",
                  (kind, id, json.dumps(obj, default=str), time.time()))
    return obj


def get(kind: str, id: str) -> Optional[Dict[str, Any]]:
    with _conn() as c:
        row = c.execute("SELECT body FROM docs WHERE kind=? AND id=?", (kind, id)).fetchone()
    return json.loads(row[0]) if row else None


def list_docs(kind: str) -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute("SELECT body FROM docs WHERE kind=? ORDER BY updated DESC", (kind,)).fetchall()
    return [json.loads(r[0]) for r in rows]


def delete(kind: str, id: str) -> bool:
    with _conn() as c:
        return c.execute("DELETE FROM docs WHERE kind=? AND id=?", (kind, id)).rowcount > 0


def add_event(kind: str, ref: Optional[str], obj: Dict[str, Any], ts: Optional[float] = None) -> int:
    with _conn() as c:
        cur = c.execute("INSERT INTO events(kind,ref,ts,body) VALUES(?,?,?,?)", (kind, ref, ts or time.time(), json.dumps(obj, default=str)))
        return int(cur.lastrowid)


def events(kind: str, ref: Optional[str] = None, since: Optional[float] = None, limit: int = 500) -> List[Dict[str, Any]]:
    q, args = "SELECT id, ts, body FROM events WHERE kind=?", [kind]
    if ref is not None:
        q += " AND ref=?"; args.append(ref)
    if since is not None:
        q += " AND ts>=?"; args.append(since)
    q += " ORDER BY ts DESC, id DESC LIMIT ?"; args.append(limit)
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    return [{"id": r[0], "ts": r[1], **json.loads(r[2])} for r in rows]
