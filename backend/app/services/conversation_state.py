from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.models import ParsedCommand


@dataclass(frozen=True)
class PendingCommandState:
    parsed: ParsedCommand
    updated_at: datetime


class PendingCommandStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        ttl: timedelta = timedelta(minutes=30),
    ) -> None:
        self.conn = conn
        self.ttl = ttl

    def get(self, session_id: str) -> PendingCommandState | None:
        row = self.conn.execute(
            """
            SELECT parsed_json, updated_at
            FROM pending_command_states
            WHERE session_id = ?
            """,
            (session_id,),
        ).fetchone()
        if row is None:
            return None

        updated_at = _parse_utc_datetime(row["updated_at"])
        if _utc_now() - updated_at > self.ttl:
            self.clear(session_id)
            return None

        return PendingCommandState(
            parsed=ParsedCommand.model_validate_json(row["parsed_json"]),
            updated_at=updated_at,
        )

    def save(self, session_id: str, parsed: ParsedCommand) -> None:
        now = _utc_now().isoformat()
        parsed_json = json.dumps(parsed.model_dump(mode="json"), ensure_ascii=False)
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO pending_command_states (session_id, parsed_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id)
                DO UPDATE SET parsed_json = excluded.parsed_json, updated_at = excluded.updated_at
                """,
                (session_id, parsed_json, now),
            )

    def clear(self, session_id: str) -> None:
        with self.conn:
            self.conn.execute(
                "DELETE FROM pending_command_states WHERE session_id = ?",
                (session_id,),
            )

    def prune_expired(self) -> int:
        cutoff = (_utc_now() - self.ttl).isoformat()
        with self.conn:
            cursor = self.conn.execute(
                "DELETE FROM pending_command_states WHERE updated_at < ?",
                (cutoff,),
            )
        return cursor.rowcount


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
