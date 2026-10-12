"""Recording Gateway outcomes into `extractor_events`."""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtractorEvent:
    operation: str
    target: str | None
    success: bool
    at: datetime
    attempts: int = 1
    duration_ms: int | None = None
    error_kind: str | None = None
    error: str | None = None


class EventRecorder(Protocol):
    def record(self, event: ExtractorEvent) -> None:
        """Store an event. Must not raise: recording never breaks a Gateway call."""
        ...


class MemoryEventRecorder:
    """Keeps events in a list. For tests."""

    def __init__(self) -> None:
        self.events: list[ExtractorEvent] = []

    def record(self, event: ExtractorEvent) -> None:
        self.events.append(event)


class SqlEventRecorder:
    """Writes events to the `extractor_events` table."""

    def __init__(self, sessions: sessionmaker[Session]) -> None:
        self._sessions = sessions

    def record(self, event: ExtractorEvent) -> None:
        try:
            with self._sessions.begin() as session:
                session.execute(
                    text(
                        "INSERT INTO extractor_events "
                        "(operation, target, success, error_kind, error, attempts, "
                        "duration_ms, at) VALUES (:operation, :target, :success, "
                        ":error_kind, :error, :attempts, :duration_ms, :at)"
                    ),
                    {
                        "operation": event.operation,
                        "target": event.target,
                        "success": int(event.success),
                        "error_kind": event.error_kind,
                        "error": event.error,
                        "attempts": event.attempts,
                        "duration_ms": event.duration_ms,
                        "at": format_timestamp(event.at),
                    },
                )
        except Exception:
            logger.exception("Could not record extractor event for %s", event.operation)


def format_timestamp(at: datetime) -> str:
    """ISO 8601 UTC with milliseconds, matching the database's own defaults."""
    at = at.astimezone(UTC)
    return at.strftime("%Y-%m-%dT%H:%M:%S.") + f"{at.microsecond // 1000:03d}Z"
