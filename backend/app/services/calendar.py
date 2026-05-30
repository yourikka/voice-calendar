from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.models import (
    Candidate,
    Conflict,
    ConfirmOperationResponse,
    EventCreate,
    EventCreateResponse,
    EventRead,
    EventUpdate,
    OperationRead,
    UndoResponse,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _load_json(value: str | None, fallback: object) -> object:
    if not value:
        return fallback
    return json.loads(value)


def _row_to_event(row: sqlite3.Row) -> EventRead:
    return EventRead(
        id=row["id"],
        calendar_id=row["calendar_id"],
        type=row["type"],
        title=row["title"],
        description=row["description"],
        start_at=datetime.fromisoformat(row["start_at"]),
        end_at=datetime.fromisoformat(row["end_at"]) if row["end_at"] else None,
        timezone=row["timezone"],
        location=row["location"],
        participants=list(_load_json(row["participants_json"], [])),
        reminders=list(_load_json(row["reminders_json"], [])),
        recurrence_rule=_load_json(row["recurrence_rule_json"], None),
        source=row["source"],
        status=row["status"],
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _event_to_dict(event: EventRead) -> dict:
    return event.model_dump(mode="json")


class CalendarService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_event(self, payload: EventCreate) -> EventCreateResponse:
        now = _utc_now()
        event_id = _new_id("evt")
        conflicts = self.check_conflicts(
            start_at=payload.start_at,
            end_at=payload.end_at,
            calendar_id=payload.calendar_id,
        )
        with self.conn:
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
                    payload.start_at.isoformat(),
                    payload.end_at.isoformat() if payload.end_at else None,
                    payload.timezone,
                    payload.location,
                    _dump(payload.participants),
                    _dump([reminder.model_dump() for reminder in payload.reminders]),
                    _dump(payload.recurrence_rule) if payload.recurrence_rule else None,
                    payload.source,
                    "confirmed",
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            event = self.get_event(event_id)
            self._log_operation("create_event", event_id, None, _event_to_dict(event))
        return EventCreateResponse(event=event, conflicts=conflicts)

    def list_events(self, start: datetime, end: datetime, calendar_id: str = "primary") -> list[EventRead]:
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
        return [_row_to_event(row) for row in rows]

    def get_event(self, event_id: str) -> EventRead:
        row = self.conn.execute(
            "SELECT * FROM events WHERE id = ? AND deleted_at IS NULL",
            (event_id,),
        ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return _row_to_event(row)

    def update_event(self, event_id: str, payload: EventUpdate) -> EventCreateResponse:
        before = self.get_event(event_id)
        update_data = payload.model_dump(exclude_unset=True)
        if not update_data:
            return EventCreateResponse(event=before, conflicts=[])

        merged = before.model_dump()
        merged.update(update_data)
        reminders = merged.get("reminders") or []
        if reminders and hasattr(reminders[0], "model_dump"):
            reminders = [item.model_dump() for item in reminders]

        now = _utc_now()
        with self.conn:
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
                    _dump(merged["participants"]),
                    _dump(reminders),
                    _dump(merged["recurrence_rule"]) if merged["recurrence_rule"] else None,
                    now.isoformat(),
                    event_id,
                ),
            )
            event = self.get_event(event_id)
            self._log_operation(
                "update_event",
                event_id,
                _event_to_dict(before),
                _event_to_dict(event),
            )
        conflicts = self.check_conflicts(
            start_at=event.start_at,
            end_at=event.end_at,
            calendar_id=event.calendar_id,
            exclude_event_id=event.id,
        )
        return EventCreateResponse(event=event, conflicts=conflicts)

    def delete_event(self, event_id: str) -> OperationRead:
        before = self.get_event(event_id)
        now = _utc_now()
        with self.conn:
            self.conn.execute(
                "UPDATE events SET deleted_at = ?, status = 'cancelled', updated_at = ? WHERE id = ?",
                (now.isoformat(), now.isoformat(), event_id),
            )
            return self._log_operation(
                "delete_event",
                event_id,
                _event_to_dict(before),
                None,
            )

    def create_delete_draft(self, event_id: str) -> OperationRead:
        before = self.get_event(event_id)
        with self.conn:
            return self._log_operation(
                "delete_event",
                event_id,
                _event_to_dict(before),
                None,
                state="awaiting_confirmation",
            )

    def create_delete_many_draft(self, event_ids: list[str]) -> OperationRead:
        before = [_event_to_dict(self.get_event(event_id)) for event_id in event_ids]
        with self.conn:
            return self._log_operation(
                "delete_events",
                None,
                before,
                None,
                state="awaiting_confirmation",
            )

    def confirm_operation(self, operation_id: str, confirmed: bool) -> ConfirmOperationResponse:
        row = self.conn.execute(
            "SELECT * FROM operation_logs WHERE id = ?",
            (operation_id,),
        ).fetchone()
        if row is None:
            raise KeyError(operation_id)
        if row["state"] != "awaiting_confirmation":
            return ConfirmOperationResponse(
                state=row["state"],
                reply_text="该操作不在待确认状态。",
            )

        if not confirmed:
            with self.conn:
                self.conn.execute(
                    "UPDATE operation_logs SET state = 'cancelled' WHERE id = ?",
                    (operation_id,),
                )
            return ConfirmOperationResponse(state="cancelled", reply_text="已取消操作。")

        operation = row["operation"]
        target_event_id = row["target_event_id"]
        before = _load_json(row["before_json"], None)
        event: EventRead | None = None
        deleted_count = None
        with self.conn:
            if operation == "delete_event" and target_event_id:
                self.conn.execute(
                    "UPDATE events SET deleted_at = ?, status = 'cancelled', updated_at = ? WHERE id = ?",
                    (_utc_now().isoformat(), _utc_now().isoformat(), target_event_id),
                )
                if before:
                    event = EventRead.model_validate(before)
                deleted_count = 1
            elif operation == "delete_events" and isinstance(before, list):
                now = _utc_now().isoformat()
                for item in before:
                    self.conn.execute(
                        "UPDATE events SET deleted_at = ?, status = 'cancelled', updated_at = ? WHERE id = ?",
                        (now, now, item["id"]),
                    )
                deleted_count = len(before)
            self.conn.execute(
                "UPDATE operation_logs SET state = 'completed' WHERE id = ?",
                (operation_id,),
            )
        if deleted_count and deleted_count > 1:
            reply_text = f"已删除 {deleted_count} 个日程。"
        elif event:
            reply_text = f"已删除{event.title}。"
        else:
            reply_text = "已执行操作。"
        return ConfirmOperationResponse(
            state="completed",
            event=event,
            deleted_count=deleted_count,
            reply_text=reply_text,
        )

    def find_events_by_title(
        self,
        title_keyword: str,
        start: datetime,
        end: datetime,
        calendar_id: str = "primary",
    ) -> list[Candidate]:
        rows = self.conn.execute(
            """
            SELECT id, title, start_at, end_at FROM events
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
                start_at=datetime.fromisoformat(row["start_at"]),
                end_at=datetime.fromisoformat(row["end_at"]) if row["end_at"] else None,
            )
            for row in rows
        ]

    def undo_last_operation(self) -> UndoResponse:
        row = self.conn.execute(
            """
            SELECT * FROM operation_logs
            WHERE state = 'completed' AND undo_expires_at >= ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (_utc_now().isoformat(),),
        ).fetchone()
        if row is None:
            return UndoResponse(state="not_available", reply_text="没有可撤销的操作。")

        operation_id = row["id"]
        operation = row["operation"]
        before = _load_json(row["before_json"], None)
        after = _load_json(row["after_json"], None)
        event: EventRead | None = None

        with self.conn:
            if operation == "create_event" and after:
                self.conn.execute(
                    "UPDATE events SET deleted_at = ?, status = 'cancelled' WHERE id = ?",
                    (_utc_now().isoformat(), after["id"]),
                )
            elif operation == "delete_events" and isinstance(before, list):
                for item in before:
                    self._restore_event(item)
            elif operation in {"delete_event", "update_event"} and before:
                self._restore_event(before)
                event = self.get_event(before["id"])
            self.conn.execute(
                "UPDATE operation_logs SET state = 'undone' WHERE id = ?",
                (operation_id,),
            )

        return UndoResponse(state="undone", event=event, reply_text="已撤销刚才的操作。")

    def check_conflicts(
        self,
        start_at: datetime,
        end_at: datetime | None,
        calendar_id: str = "primary",
        exclude_event_id: str | None = None,
    ) -> list[Conflict]:
        effective_end = end_at or start_at
        params: list[str] = [calendar_id, effective_end.isoformat(), start_at.isoformat()]
        exclude_clause = ""
        if exclude_event_id:
            exclude_clause = "AND id != ?"
            params.append(exclude_event_id)
        rows = self.conn.execute(
            f"""
            SELECT id, title, start_at, end_at FROM events
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
                start_at=datetime.fromisoformat(row["start_at"]),
                end_at=datetime.fromisoformat(row["end_at"]) if row["end_at"] else None,
            )
            for row in rows
        ]

    def _log_operation(
        self,
        operation: str,
        target_event_id: str | None,
        before: dict | None,
        after: dict | None,
        state: str = "completed",
    ) -> OperationRead:
        now = _utc_now()
        operation_id = _new_id("op")
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
                _dump(before) if before else None,
                _dump(after) if after else None,
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

    def _restore_event(self, data: dict) -> None:
        self.conn.execute(
            """
            UPDATE events
            SET calendar_id = ?, type = ?, title = ?, description = ?, start_at = ?,
                end_at = ?, timezone = ?, location = ?, participants_json = ?,
                reminders_json = ?, recurrence_rule_json = ?, source = ?,
                status = ?, updated_at = ?, deleted_at = NULL
            WHERE id = ?
            """,
            (
                data["calendar_id"],
                data["type"],
                data["title"],
                data["description"],
                data["start_at"],
                data["end_at"],
                data["timezone"],
                data["location"],
                _dump(data["participants"]),
                _dump(data["reminders"]),
                _dump(data["recurrence_rule"]) if data["recurrence_rule"] else None,
                data["source"],
                data["status"],
                _utc_now().isoformat(),
                data["id"],
            ),
        )
