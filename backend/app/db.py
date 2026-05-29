from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

from app.config import Settings, get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    calendar_id TEXT NOT NULL,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    start_at TEXT NOT NULL,
    end_at TEXT,
    timezone TEXT NOT NULL,
    location TEXT,
    participants_json TEXT NOT NULL DEFAULT '[]',
    reminders_json TEXT NOT NULL DEFAULT '[]',
    recurrence_rule_json TEXT,
    source TEXT NOT NULL DEFAULT 'web',
    status TEXT NOT NULL DEFAULT 'confirmed',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS operation_logs (
    id TEXT PRIMARY KEY,
    operation TEXT NOT NULL,
    target_event_id TEXT,
    before_json TEXT,
    after_json TEXT,
    state TEXT NOT NULL,
    created_at TEXT NOT NULL,
    undo_expires_at TEXT
);

CREATE TABLE IF NOT EXISTS news_items (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    category TEXT NOT NULL,
    region TEXT NOT NULL,
    source_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    published_at TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    language TEXT NOT NULL,
    hot_score REAL NOT NULL
);
"""


class Database:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.path = self.settings.database_path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)


def initialize_database(settings: Settings | None = None) -> None:
    Database(settings).initialize()


def get_connection() -> Iterator[sqlite3.Connection]:
    db = Database()
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def reset_database(path: Path) -> None:
    if path.exists():
        path.unlink()
    Database(Settings(database_path=path)).initialize()
