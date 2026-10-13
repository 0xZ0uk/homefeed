"""Extraction health from `extractor_events`, for the status page.

Every Gateway operation that reaches YouTube records an event (see
`homefeed_core.gateway.events`). This module aggregates the events of a recent window
per operation and judges each operation's health:

- Failures whose kind says something about the target rather than the extractor (a
  removed video, an unsupported URL, an expired stream URL) are counted, but they don't
  make an operation unhealthy: YouTube answered, there was just nothing to get.
- An operation is `failing` when its latest `FAILING_STREAK` events in the window (or
  all of them, if it has fewer) were breakage failures, `degraded` when it had any
  breakage failure in the window, `ok` otherwise, and `unknown` with no events at all.
- The overall health is the worst of the operations' (`unknown` without events).

The live smoke test (`homefeed_core.smoke_test`) records one summary event per run under
`SMOKE_TEST_OPERATION`; it is reported on its own (the latest run, whenever it was)
rather than as an operation, since each of its checks is recorded as an operation too.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core.gateway.events import format_timestamp

DEFAULT_HOURS = 24
MAX_HOURS = 24 * 30
RECENT_FAILURES_LIMIT = 20
FAILING_STREAK = 3
SMOKE_TEST_OPERATION = "smoke_test"

# Failure kinds about the target (see homefeed_core.gateway.errors), not extraction.
TARGET_ERROR_KINDS = frozenset(
    {"unavailable", "unsupported_url", "media_url_expired", "range_not_satisfiable"}
)

type Health = Literal["ok", "degraded", "failing", "unknown"]

_SEVERITY: dict[Health, int] = {"unknown": 0, "ok": 1, "degraded": 2, "failing": 3}


@dataclass(frozen=True)
class OperationStatus:
    operation: str
    health: Health
    total: int
    successes: int
    failures: int  # all failures, including target failures
    breakage_failures: int  # failures that point at the extractor (not the target)
    success_rate: float | None  # successes / total
    avg_duration_ms: int | None
    last_at: datetime
    last_success_at: datetime | None
    last_failure_at: datetime | None
    last_error_kind: str | None  # of the latest failure in the window
    last_error: str | None


@dataclass(frozen=True)
class FailedEvent:
    id: int
    operation: str
    target: str | None
    error_kind: str | None
    error: str | None
    attempts: int
    at: datetime
    breakage: bool  # False for target failures (see TARGET_ERROR_KINDS)


@dataclass(frozen=True)
class SmokeTestRun:
    at: datetime
    success: bool
    error: str | None  # which checks failed and why
    duration_ms: int | None


@dataclass(frozen=True)
class ExtractorStatus:
    since: datetime
    hours: int
    health: Health
    operations: list[OperationStatus]  # by operation name
    recent_failures: list[FailedEvent]  # newest first
    last_smoke_test: SmokeTestRun | None


def is_breakage(error_kind: str | None) -> bool:
    """Whether a failure of this kind suggests the extractor is broken."""
    return error_kind not in TARGET_ERROR_KINDS


def operation_health(recent_breakage: Sequence[bool], breakage_failures: int) -> Health:
    """Health from an operation's latest outcomes, newest first (True for a breakage
    failure, False for anything else), and its breakage failures in the window."""
    if not recent_breakage:
        return "unknown"
    streak = recent_breakage[:FAILING_STREAK]
    if all(streak):
        return "failing"
    if breakage_failures > 0:
        return "degraded"
    return "ok"


def worst_health(healths: Sequence[Health]) -> Health:
    worst: Health = "unknown"
    for health in healths:
        if _SEVERITY[health] > _SEVERITY[worst]:
            worst = health
    return worst


def extractor_status(
    session: Session,
    *,
    hours: int = DEFAULT_HOURS,
    now: datetime | None = None,
    failures_limit: int = RECENT_FAILURES_LIMIT,
) -> ExtractorStatus:
    """Extraction health over the last `hours` (1 to `MAX_HOURS`)."""
    if not 1 <= hours <= MAX_HOURS:
        raise ValueError(f"hours must be between 1 and {MAX_HOURS}")
    since = (now or datetime.now(UTC)).astimezone(UTC) - timedelta(hours=hours)
    params = {"since": format_timestamp(since), "smoke": SMOKE_TEST_OPERATION}
    target_kinds = ", ".join(f"'{kind}'" for kind in sorted(TARGET_ERROR_KINDS))
    breakage = f"(success = 0 AND (error_kind IS NULL OR error_kind NOT IN ({target_kinds})))"

    aggregates = session.execute(
        text(
            f"""
            SELECT operation, COUNT(*), SUM(success), SUM({breakage}), AVG(duration_ms),
                   MAX(at), MAX(CASE WHEN success = 1 THEN at END),
                   MAX(CASE WHEN success = 0 THEN at END)
            FROM extractor_events
            WHERE at >= :since AND operation != :smoke
            GROUP BY operation
            ORDER BY operation
            """
        ),
        params,
    ).all()

    # The latest few outcomes per operation, for the failing streak.
    streaks: dict[str, list[bool]] = {}
    for operation, failed in session.execute(
        text(
            f"""
            SELECT operation, failed FROM (
                SELECT operation, {breakage} AS failed,
                       ROW_NUMBER() OVER (PARTITION BY operation ORDER BY at DESC, id DESC) AS n
                FROM extractor_events
                WHERE at >= :since AND operation != :smoke
            )
            WHERE n <= :streak
            ORDER BY operation, n
            """
        ),
        {**params, "streak": FAILING_STREAK},
    ):
        streaks.setdefault(operation, []).append(bool(failed))

    last_errors: dict[str, tuple[str | None, str | None]] = {}
    for operation, error_kind, error in session.execute(
        text(
            """
            SELECT operation, error_kind, error FROM (
                SELECT operation, error_kind, error,
                       ROW_NUMBER() OVER (PARTITION BY operation ORDER BY at DESC, id DESC) AS n
                FROM extractor_events
                WHERE at >= :since AND operation != :smoke AND success = 0
            )
            WHERE n = 1
            """
        ),
        params,
    ):
        last_errors[operation] = (error_kind, error)

    operations: list[OperationStatus] = []
    for row in aggregates:
        operation, total, successes, breakage_failures, avg_ms, last_at, last_ok, last_fail = row
        error_kind, error = last_errors.get(operation, (None, None))
        operations.append(
            OperationStatus(
                operation=operation,
                health=operation_health(streaks.get(operation, []), breakage_failures),
                total=total,
                successes=successes,
                failures=total - successes,
                breakage_failures=breakage_failures,
                success_rate=successes / total,
                avg_duration_ms=round(avg_ms) if avg_ms is not None else None,
                last_at=_parse(last_at),
                last_success_at=_parse(last_ok) if last_ok else None,
                last_failure_at=_parse(last_fail) if last_fail else None,
                last_error_kind=error_kind,
                last_error=error,
            )
        )

    recent_failures = [
        FailedEvent(
            id=id_,
            operation=operation,
            target=target,
            error_kind=error_kind,
            error=error,
            attempts=attempts,
            at=_parse(at),
            breakage=is_breakage(error_kind),
        )
        for id_, operation, target, error_kind, error, attempts, at in session.execute(
            text(
                """
                SELECT id, operation, target, error_kind, error, attempts, at
                FROM extractor_events
                WHERE at >= :since AND operation != :smoke AND success = 0
                ORDER BY at DESC, id DESC
                LIMIT :limit
                """
            ),
            {**params, "limit": failures_limit},
        )
    ]

    smoke = session.execute(
        text(
            """
            SELECT at, success, error, duration_ms FROM extractor_events
            WHERE operation = :smoke ORDER BY at DESC, id DESC LIMIT 1
            """
        ),
        params,
    ).first()
    last_smoke_test = (
        SmokeTestRun(
            at=_parse(smoke[0]), success=bool(smoke[1]), error=smoke[2], duration_ms=smoke[3]
        )
        if smoke
        else None
    )

    return ExtractorStatus(
        since=since,
        hours=hours,
        health=worst_health([operation.health for operation in operations]),
        operations=operations,
        recent_failures=recent_failures,
        last_smoke_test=last_smoke_test,
    )


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)
