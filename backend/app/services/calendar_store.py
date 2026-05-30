from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo

from app.models import Candidate, Conflict, EventCreate, EventRead, EventUpdate, OperationRead


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Datetime values must include timezone information.")
    return value.astimezone(timezone.utc)


def store_datetime(value: datetime) -> str:
    return to_utc(value).isoformat()


def display_datetime(value: str, timezone_name: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(ZoneInfo(timezone_name))


def dump_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def load_json(value: str | None, fallback: object) -> object:
    if not value:
        return fallback
    return json.loads(value)


@dataclass(frozen=True)
class EventWrite:
    id: str
    start_at: datetime
    end_at: datetime | None
    now: datetime


class EventRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def insert(self, payload: EventCreate) -> EventWrite:
        now = utc_now()
        start_at = to_utc(payload.start_at)
        end_at = to_utc(payload.end_at) if payload.end_at else None
        if end_at is not None and end_at < start_at:
            raise ValueError("Event end_at must be greater than or equal to start_at.")

        event_id = new_id("evt")
        self.conn.execute(
            """
            INSERT INTO events (
                id, calendar_id, type, title, description, start_at, end_at, timezone,
                location, participants_json, reminders_json, recurrence_rule_json,
                source, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                payload.calendar_id,
                payload.type,
                payload.title,
                payload.description,
                start_at.isoformat(),
                end_at.isoformat() if end_at else None,
                payload.timezone,
                payload.location,
                dump_json(payload.participants),
                dump_json([reminder.model_dump() for reminder in payload.reminders]),
                dump_json(payload.recurrence_rule) if payload.recurrence_rule else None,
                payload.source,
                "confirmed",
                now.isoformat(),
                now.isoformat(),
            ),
        )
        return EventWrite(id=event_id, start_at=start_at, end_at=end_at, now=now)

    def list(self, start: datetime, end: datetime, calendar_id: str = "primary") -> list[EventRead]:
        start = to_utc(start)
        end = to_utc(end)
        if end < start:
            raise ValueError("List end must be greater than or equal to start.")
        rows = self.conn.execute(
            """
            SELECT * FROM events
            WHERE calendar_id = ?
              AND deleted_at IS NULL
              AND status = 'confirmed'
              AND start_at < ?
              AND COALESCE(end_at, start_at) >= ?
            ORDER BY start_at ASC
            """,
            (calendar_id, end.isoformat(), start.isoformat()),
        ).fetchall()
        return [row_to_event(row) for row in rows]

    def get(self, event_id: str) -> EventRead:
        row = self.conn.execute(
            "SELECT * FROM events WHERE id = ? AND deleted_at IS NULL",
            (event_id,),
        ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return row_to_event(row)

    def update(self, event_id: str, before: EventRead, payload: EventUpdate) -> EventRead:
        merged = before.model_dump()
        merged.update(payload.model_dump(exclude_unset=True))
        merged["start_at"] = to_utc(merged["start_at"])
        if merged["end_at"] is not None:
            merged["end_at"] = to_utc(merged["end_at"])
            if merged["end_at"] < merged["start_at"]:
                raise ValueError("Event end_at must be greater than or equal to start_at.")

        reminders = merged.get("reminders") or []
        if reminders and hasattr(reminders[0], "model_dump"):
            reminders = [item.model_dump() for item in reminders]

        now = utc_now()
        self.conn.execute(
            """
            UPDATE events
            SET title = ?, description = ?, start_at = ?, end_at = ?, timezone = ?,
                location = ?, participants_json = ?, reminders_json = ?,
                recurrence_rule_json = ?, updated_at = ?
            WHERE id = ? AND deleted_at IS NULL
            """,
            (
                merged["title"],
                merged["description"],
                merged["start_at"].isoformat(),
                merged["end_at"].isoformat() if merged["end_at"] else None,
                merged["timezone"],
                merged["location"],
                dump_json(merged["participants"]),
                dump_json(reminders),
                dump_json(merged["recurrence_rule"]) if merged["recurrence_rule"] else None,
                now.isoformat(),
                event_id,
            ),
        )
        return self.get(event_id)

    def list_undelivered_reminders(self, channel: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT
                e.id AS event_id,
                e.title,
                e.description,
                e.start_at,
                e.timezone,
                e.source,
                nd.id AS delivery_id
            FROM events e
            LEFT JOIN notification_deliveries nd
              ON nd.event_id = e.id AND nd.channel = ?
            WHERE e.deleted_at IS NULL
              AND e.status = 'confirmed'
              AND e.type = 'reminder'
              AND nd.id IS NULL
            ORDER BY e.start_at ASC
            """,
            (channel,),
        ).fetchall()

    def soft_delete(self, event_id: str, *, now: datetime | None = None) -> None:
        current = now or utc_now()
        self.conn.execute(
            "UPDATE events SET deleted_at = ?, status = 'cancelled', updated_at = ? WHERE id = ?",
            (current.isoformat(), current.isoformat(), event_id),
        )

    def find_by_title(
        self,
        title_keyword: str,
        start: datetime,
        end: datetime,
        calendar_id: str = "primary",
    ) -> list[Candidate]:
        start = to_utc(start)
        end = to_utc(end)
        if end < start:
            raise ValueError("Find end must be greater than or equal to start.")
        rows = self.conn.execute(
            """
            SELECT id, title, start_at, end_at, timezone FROM events
            WHERE calendar_id = ?
              AND deleted_at IS NULL
              AND status = 'confirmed'
              AND start_at < ?
              AND COALESCE(end_at, start_at) >= ?
              AND title LIKE ?
            ORDER BY start_at ASC
            """,
            (calendar_id, end.isoformat(), start.isoformat(), f"%{title_keyword}%"),
        ).fetchall()
        return [
            Candidate(
                id=row["id"],
                title=row["title"],
                start_at=display_datetime(row["start_at"], row["timezone"]),
                end_at=display_datetime(row["end_at"], row["timezone"]) if row["end_at"] else None,
            )
            for row in rows
        ]

    def check_conflicts(
        self,
        start_at: datetime,
        end_at: datetime | None,
        calendar_id: str = "primary",
        exclude_event_id: str | None = None,
    ) -> list[Conflict]:
        start_at = to_utc(start_at)
        effective_end = to_utc(end_at) if end_at else start_at
        if effective_end < start_at:
            raise ValueError("Conflict end_at must be greater than or equal to start_at.")

        params: list[str] = [calendar_id, effective_end.isoformat(), start_at.isoformat()]
        exclude_clause = ""
        if exclude_event_id:
            exclude_clause = "AND id != ?"
            params.append(exclude_event_id)
        rows = self.conn.execute(
            f"""
            SELECT id, title, start_at, end_at, timezone FROM events
            WHERE calendar_id = ?
              AND deleted_at IS NULL
              AND status = 'confirmed'
              AND start_at < ?
              AND COALESCE(end_at, start_at) > ?
              {exclude_clause}
            ORDER BY start_at ASC
            """,
            params,
        ).fetchall()
        return [
            Conflict(
                id=row["id"],
                title=row["title"],
                start_at=display_datetime(row["start_at"], row["timezone"]),
                end_at=display_datetime(row["end_at"], row["timezone"]) if row["end_at"] else None,
            )
            for row in rows
        ]


class OperationLogRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(
        self,
        *,
        operation: str,
        target_event_id: str | None,
        before_json: str | None,
        after_json: str | None,
        state: str = "completed",
    ) -> OperationRead:
        now = utc_now()
        operation_id = new_id("op")
        undo_expires_at = now + timedelta(minutes=10)
        self.conn.execute(
            """
            INSERT INTO operation_logs (
                id, operation, target_event_id, before_json, after_json, state,
                created_at, undo_expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operation_id,
                operation,
                target_event_id,
                before_json,
                after_json,
                state,
                now.isoformat(),
                undo_expires_at.isoformat(),
            ),
        )
        return OperationRead(
            id=operation_id,
            operation=operation,
            target_event_id=target_event_id,
            state=state,
            created_at=now,
            undo_expires_at=undo_expires_at,
        )

    def get(self, operation_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT * FROM operation_logs WHERE id = ?",
            (operation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(operation_id)
        return row

    def mark_state(self, operation_id: str, state: str) -> None:
        self.conn.execute(
            "UPDATE operation_logs SET state = ? WHERE id = ?",
            (state, operation_id),
        )

    def latest_undoable(self) -> sqlite3.Row | None:
        return self.conn.execute(
            """
            SELECT * FROM operation_logs
            WHERE state = 'completed' AND undo_expires_at >= ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (utc_now().isoformat(),),
        ).fetchone()


class NotificationDeliveryRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_pending(self, *, event_id: str, channel: str, scheduled_at: datetime, now: datetime) -> str:
        delivery_id = new_id("notify")
        self.conn.execute(
            """
            INSERT INTO notification_deliveries (
                id, event_id, channel, scheduled_at, delivered_at, status, created_at
            ) VALUES (?, ?, ?, ?, NULL, 'pending', ?)
            """,
            (
                delivery_id,
                event_id,
                channel,
                store_datetime(scheduled_at),
                now.isoformat(),
            ),
        )
        return delivery_id

    def acknowledge(self, delivery_id: str, channel: str) -> bool:
        row = self.conn.execute(
            "SELECT id FROM notification_deliveries WHERE id = ? AND channel = ?",
            (delivery_id, channel),
        ).fetchone()
        if row is None:
            return False
        self.conn.execute(
            """
            UPDATE notification_deliveries
            SET status = 'delivered', delivered_at = ?
            WHERE id = ? AND channel = ?
            """,
            (utc_now().isoformat(), delivery_id, channel),
        )
        return True


def row_to_event(row: sqlite3.Row) -> EventRead:
    return EventRead(
        id=row["id"],
        calendar_id=row["calendar_id"],
        type=row["type"],
        title=row["title"],
        description=row["description"],
        start_at=display_datetime(row["start_at"], row["timezone"]),
        end_at=display_datetime(row["end_at"], row["timezone"]) if row["end_at"] else None,
        timezone=row["timezone"],
        location=row["location"],
        participants=list(load_json(row["participants_json"], [])),
        reminders=list(load_json(row["reminders_json"], [])),
        recurrence_rule=load_json(row["recurrence_rule_json"], None),
        source=row["source"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )
