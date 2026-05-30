import sqlite3
from pathlib import Path

from app.config import Settings
from app.db import Database


def test_database_initialization_tracks_migrations_and_indexes(tmp_path: Path) -> None:
    db_path = tmp_path / "calendar.db"
    Database(Settings(database_path=db_path)).initialize()

    with sqlite3.connect(db_path) as conn:
        versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations")]
        indexes = {
            row[1]
            for row in conn.execute(
                "SELECT type, name FROM sqlite_master WHERE type = 'index'"
            )
        }
        notification_foreign_keys = conn.execute(
            "PRAGMA foreign_key_list(notification_deliveries)"
        ).fetchall()

    assert versions == [1, 2, 3]
    assert "idx_events_calendar_time" in indexes
    assert "idx_pending_command_updated" in indexes
    assert any(row[2] == "events" for row in notification_foreign_keys)


def test_database_migration_adds_notification_foreign_key_to_existing_database(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE events (
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
            CREATE TABLE notification_deliveries (
                id TEXT PRIMARY KEY,
                event_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                scheduled_at TEXT NOT NULL,
                delivered_at TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(event_id, channel)
            );
            CREATE TABLE operation_logs (
                id TEXT PRIMARY KEY,
                operation TEXT NOT NULL,
                target_event_id TEXT,
                before_json TEXT,
                after_json TEXT,
                state TEXT NOT NULL,
                created_at TEXT NOT NULL,
                undo_expires_at TEXT
            );
            CREATE TABLE news_items (
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
            CREATE TABLE pending_command_states (
                session_id TEXT PRIMARY KEY,
                parsed_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO schema_migrations(version) VALUES (1), (2);
            """
        )

    Database(Settings(database_path=db_path)).initialize()

    with sqlite3.connect(db_path) as conn:
        foreign_keys = conn.execute("PRAGMA foreign_key_list(notification_deliveries)").fetchall()
        versions = [row[0] for row in conn.execute("SELECT version FROM schema_migrations")]

    assert 3 in versions
    assert any(row[2] == "events" for row in foreign_keys)
