from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from app.models import (
    Candidate,
    Conflict,
    ConfirmOperationResponse,
    DueReminderRead,
    EventCreate,
    EventCreateResponse,
    EventRead,
    EventUpdate,
    NotificationAcknowledgeResponse,
    OperationRead,
    UndoResponse,
)
from app.services.calendar_store import (
    EventRepository,
    NotificationDeliveryRepository,
    OperationLogRepository,
    display_datetime,
    store_datetime,
    to_utc,
    utc_now,
)


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _load_json(value: str | None, fallback: object) -> object:
    if not value:
        return fallback
    return json.loads(value)


def _event_to_dict(event: EventRead) -> dict:
    return event.model_dump(mode="json")


class CalendarService:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.events = EventRepository(conn)
        self.operations = OperationLogRepository(conn)
        self.deliveries = NotificationDeliveryRepository(conn)

    def list_due_reminders(
        self,
        *,
        channel: str,
        now: datetime | None = None,
        lookback_seconds: int = 300,
        limit: int = 20,
    ) -> list[DueReminderRead]:
        current = to_utc(now) if now else utc_now()
        window_start = current - timedelta(seconds=lookback_seconds)
        rows = self.events.list_undelivered_reminders(channel)

        reminders: list[DueReminderRead] = []
        with self.conn:
            for row in rows:
                start_at = display_datetime(row["start_at"], row["timezone"])
                start_at_utc = to_utc(start_at)
                if start_at_utc < window_start or start_at_utc > current:
                    continue
                delivery_id = self.deliveries.create_pending(
                    event_id=row["event_id"],
                    channel=channel,
                    scheduled_at=start_at,
                    now=current,
                )
                reminders.append(
                    DueReminderRead(
                        delivery_id=delivery_id,
                        event_id=row["event_id"],
                        title=row["title"],
                        description=row["description"] or "",
                        start_at=start_at,
                        timezone=row["timezone"],
                        source=row["source"],
                    )
                )
                if len(reminders) >= limit:
                    break
        return reminders

    def acknowledge_delivery(self, delivery_id: str, channel: str) -> NotificationAcknowledgeResponse:
        with self.conn:
            acknowledged = self.deliveries.acknowledge(delivery_id, channel)
        if not acknowledged:
            raise KeyError(delivery_id)
        return NotificationAcknowledgeResponse(status="delivered")

    def create_event(self, payload: EventCreate) -> EventCreateResponse:
        conflicts = self.check_conflicts(
            start_at=payload.start_at,
            end_at=payload.end_at,
            calendar_id=payload.calendar_id,
        )
        with self.conn:
            written = self.events.insert(payload)
            event = self.get_event(written.id)
            self._log_operation("create_event", written.id, None, _event_to_dict(event))
        return EventCreateResponse(event=event, conflicts=conflicts)

    def list_events(self, start: datetime, end: datetime, calendar_id: str = "primary") -> list[EventRead]:
        return self.events.list(start, end, calendar_id)

    def get_event(self, event_id: str) -> EventRead:
        return self.events.get(event_id)

    def update_event(self, event_id: str, payload: EventUpdate) -> EventCreateResponse:
        before = self.get_event(event_id)
        update_data = payload.model_dump(exclude_unset=True)
        if not update_data:
            return EventCreateResponse(event=before, conflicts=[])

        with self.conn:
            event = self.events.update(event_id, before, payload)
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
        with self.conn:
            self.events.soft_delete(event_id)
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
        row = self.operations.get(operation_id)
        if row["state"] != "awaiting_confirmation":
            return ConfirmOperationResponse(
                state=row["state"],
                reply_text="该操作不在待确认状态。",
            )

        if not confirmed:
            with self.conn:
                self.operations.mark_state(operation_id, "cancelled")
            return ConfirmOperationResponse(state="cancelled", reply_text="已取消操作。")

        operation = row["operation"]
        target_event_id = row["target_event_id"]
        before = _load_json(row["before_json"], None)
        event: EventRead | None = None
        deleted_count = None
        with self.conn:
            if operation == "delete_event" and target_event_id:
                self.events.soft_delete(target_event_id)
                if before:
                    event = EventRead.model_validate(before)
                deleted_count = 1
            elif operation == "delete_events" and isinstance(before, list):
                for item in before:
                    self.events.soft_delete(item["id"])
                deleted_count = len(before)
            self.operations.mark_state(operation_id, "completed")

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
        return self.events.find_by_title(title_keyword, start, end, calendar_id)

    def undo_last_operation(self) -> UndoResponse:
        row = self.operations.latest_undoable()
        if row is None:
            return UndoResponse(state="not_available", reply_text="没有可撤销的操作。")

        operation_id = row["id"]
        operation = row["operation"]
        before = _load_json(row["before_json"], None)
        after = _load_json(row["after_json"], None)
        event: EventRead | None = None

        with self.conn:
            if operation == "create_event" and after:
                self.events.soft_delete(after["id"])
            elif operation == "delete_events" and isinstance(before, list):
                for item in before:
                    self._restore_event(item)
            elif operation in {"delete_event", "update_event"} and before:
                self._restore_event(before)
                event = self.get_event(before["id"])
            self.operations.mark_state(operation_id, "undone")

        return UndoResponse(state="undone", event=event, reply_text="已撤销刚才的操作。")

    def check_conflicts(
        self,
        start_at: datetime,
        end_at: datetime | None,
        calendar_id: str = "primary",
        exclude_event_id: str | None = None,
    ) -> list[Conflict]:
        return self.events.check_conflicts(start_at, end_at, calendar_id, exclude_event_id)

    def _log_operation(
        self,
        operation: str,
        target_event_id: str | None,
        before: dict | list[dict] | None,
        after: dict | None,
        state: str = "completed",
    ) -> OperationRead:
        return self.operations.create(
            operation=operation,
            target_event_id=target_event_id,
            before_json=_dump(before) if before else None,
            after_json=_dump(after) if after else None,
            state=state,
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
                store_datetime(datetime.fromisoformat(data["start_at"])),
                store_datetime(datetime.fromisoformat(data["end_at"])) if data["end_at"] else None,
                data["timezone"],
                data["location"],
                _dump(data["participants"]),
                _dump(data["reminders"]),
                _dump(data["recurrence_rule"]) if data["recurrence_rule"] else None,
                data["source"],
                data["status"],
                utc_now().isoformat(),
                data["id"],
            ),
        )
