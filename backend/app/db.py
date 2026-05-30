from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
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

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    scheduled_at TEXT NOT NULL,
    delivered_at TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(event_id) REFERENCES events(id),
    UNIQUE(event_id, channel)
);

CREATE TABLE IF NOT EXISTS pending_command_states (
    session_id TEXT PRIMARY KEY,
    parsed_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""

MIGRATIONS = {
    1: (
        "CREATE INDEX IF NOT EXISTS idx_events_calendar_time "
        "ON events(calendar_id, start_at, end_at, status, deleted_at)",
        "CREATE INDEX IF NOT EXISTS idx_events_title "
        "ON events(calendar_id, title, start_at)",
        "CREATE INDEX IF NOT EXISTS idx_operation_logs_undo "
        "ON operation_logs(state, undo_expires_at, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_notification_due "
        "ON notification_deliveries(channel, event_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_news_region_category_score "
        "ON news_items(region, category, hot_score, published_at)",
        "CREATE INDEX IF NOT EXISTS idx_pending_command_updated "
        "ON pending_command_states(updated_at)",
    ),
    2: "_normalize_event_datetimes",
    3: "_ensure_notification_delivery_foreign_key",
}


class Database:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.path = self.settings.database_path

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA)
            _apply_migrations(conn)


def initialize_database(settings: Settings | None = None) -> None:
    Database(settings).initialize()


def get_connection() -> Iterator[sqlite3.Connection]:
    db = Database()
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def get_connection_context(settings: Settings | None = None) -> Iterator[sqlite3.Connection]:
    db = Database(settings)
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def reset_database(path: Path) -> None:
    if path.exists():
        path.unlink()
    Database(Settings(database_path=path)).initialize()


def _apply_migrations(conn: sqlite3.Connection) -> None:
    applied = {
        row["version"]
        for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
    }
    for version in sorted(MIGRATIONS):
        if version in applied:
            continue
        migration = MIGRATIONS[version]
        if migration == "_normalize_event_datetimes":
            _normalize_event_datetimes(conn)
        elif migration == "_ensure_notification_delivery_foreign_key":
            _ensure_notification_delivery_foreign_key(conn)
        else:
            for statement in migration:
                conn.execute(statement)
        conn.execute("INSERT INTO schema_migrations (version) VALUES (?)", (version,))


def _normalize_event_datetimes(conn: sqlite3.Connection) -> None:
    rows = conn.execute("SELECT id, start_at, end_at FROM events").fetchall()
    for row in rows:
        conn.execute(
            "UPDATE events SET start_at = ?, end_at = ? WHERE id = ?",
            (
                _utc_iso(row["start_at"]),
                _utc_iso(row["end_at"]) if row["end_at"] else None,
                row["id"],
            ),
        )


def _utc_iso(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _ensure_notification_delivery_foreign_key(conn: sqlite3.Connection) -> None:
    foreign_keys = conn.execute("PRAGMA foreign_key_list(notification_deliveries)").fetchall()
    if any(row["table"] == "events" for row in foreign_keys):
        return

    conn.execute(
        """
        CREATE TABLE notification_deliveries_new (
            id TEXT PRIMARY KEY,
            event_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            scheduled_at TEXT NOT NULL,
            delivered_at TEXT,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(event_id) REFERENCES events(id),
            UNIQUE(event_id, channel)
        )
        """
    )
    conn.execute(
        """
        INSERT INTO notification_deliveries_new (
            id, event_id, channel, scheduled_at, delivered_at, status, created_at
        )
        SELECT
            nd.id,
            nd.event_id,
            nd.channel,
            nd.scheduled_at,
            nd.delivered_at,
            nd.status,
            nd.created_at
        FROM notification_deliveries nd
        JOIN events e ON e.id = nd.event_id
        """
    )
    conn.execute("DROP TABLE notification_deliveries")
    conn.execute("ALTER TABLE notification_deliveries_new RENAME TO notification_deliveries")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_notification_due "
        "ON notification_deliveries(channel, event_id, status)"
    )
