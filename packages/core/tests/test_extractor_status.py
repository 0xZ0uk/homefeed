from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import open_database
from homefeed_core.extractor_status import (
    SMOKE_TEST_OPERATION,
    ExtractorStatus,
    extractor_status,
    operation_health,
    worst_health,
)
from homefeed_core.gateway import ExtractorEvent, SqlEventRecorder

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def record(
    sessions: sessionmaker[Session],
    operation: str,
    *,
    minutes_ago: float,
    error_kind: str | None = None,
    target: str | None = "jNQXAC9IVRw",
    duration_ms: int | None = 100,
) -> None:
    SqlEventRecorder(sessions).record(
        ExtractorEvent(
            operation=operation,
            target=target,
            success=error_kind is None,
            at=NOW - timedelta(minutes=minutes_ago),
            duration_ms=duration_ms,
            error_kind=error_kind,
            error=f"{error_kind} error" if error_kind else None,
        )
    )


def status(sessions: sessionmaker[Session], **kwargs: int) -> ExtractorStatus:
    with sessions() as session:
        return extractor_status(session, now=NOW, **kwargs)


@pytest.mark.parametrize(
    ("recent", "breakage_failures", "expected"),
    [
        ([], 0, "unknown"),
        ([False, False], 0, "ok"),
        ([False, True, True], 2, "degraded"),
        ([True, True, False], 2, "degraded"),
        ([True, True, True, False], 3, "failing"),
        ([True], 1, "failing"),
        ([True, True], 2, "failing"),
    ],
)
def test_operation_health(recent: list[bool], breakage_failures: int, expected: str) -> None:
    assert operation_health(recent, breakage_failures) == expected


def test_worst_health() -> None:
    assert worst_health([]) == "unknown"
    assert worst_health(["ok", "unknown"]) == "ok"
    assert worst_health(["ok", "failing", "degraded"]) == "failing"


def test_empty_status(sessions: sessionmaker[Session]) -> None:
    result = status(sessions)

    assert result.health == "unknown"
    assert result.hours == 24
    assert result.since == NOW - timedelta(hours=24)
    assert result.operations == []
    assert result.recent_failures == []
    assert result.last_smoke_test is None


def test_aggregates_per_operation_within_the_window(sessions: sessionmaker[Session]) -> None:
    record(sessions, "get_video", minutes_ago=30, duration_ms=100)
    record(sessions, "get_video", minutes_ago=20, duration_ms=300)
    record(sessions, "get_video", minutes_ago=10, error_kind="unavailable", duration_ms=None)
    record(sessions, "get_video", minutes_ago=25 * 60)  # outside the window
    record(sessions, "search", minutes_ago=5, target="hand planes")

    result = status(sessions)

    assert [op.operation for op in result.operations] == ["get_video", "search"]
    video = result.operations[0]
    assert (video.total, video.successes, video.failures, video.breakage_failures) == (3, 2, 1, 0)
    assert video.success_rate == pytest.approx(2 / 3)
    assert video.avg_duration_ms == 200
    assert video.last_at == NOW - timedelta(minutes=10)
    assert video.last_success_at == NOW - timedelta(minutes=20)
    assert video.last_failure_at == NOW - timedelta(minutes=10)
    assert (video.last_error_kind, video.last_error) == ("unavailable", "unavailable error")
    # A removed video is the target's fault, not the extractor's.
    assert video.health == "ok"
    assert result.health == "ok"


def test_breakage_failures_make_an_operation_unhealthy(sessions: sessionmaker[Session]) -> None:
    record(sessions, "get_formats", minutes_ago=50)
    record(sessions, "get_formats", minutes_ago=40, error_kind="rate_limited")
    record(sessions, "get_formats", minutes_ago=30)
    for minutes in (20, 10, 5):
        record(sessions, "get_related", minutes_ago=minutes, error_kind="extraction")
    record(sessions, "get_video", minutes_ago=1)

    result = status(sessions)

    healths = {op.operation: op.health for op in result.operations}
    assert healths == {"get_formats": "degraded", "get_related": "failing", "get_video": "ok"}
    assert result.health == "failing"


def test_recent_failures_newest_first_and_limited(sessions: sessionmaker[Session]) -> None:
    record(sessions, "get_video", minutes_ago=30, error_kind="unavailable")
    record(sessions, "search", minutes_ago=20, error_kind="extraction", target="q")
    record(sessions, "get_video", minutes_ago=10)
    record(sessions, "resolve_url", minutes_ago=5, error_kind="unsupported_url", target="x")

    result = status(sessions, failures_limit=2)

    assert [(f.operation, f.target, f.breakage) for f in result.recent_failures] == [
        ("resolve_url", "x", False),
        ("search", "q", True),
    ]
    assert result.recent_failures[1].error_kind == "extraction"
    assert result.recent_failures[1].at == NOW - timedelta(minutes=20)


def test_smoke_test_runs_are_reported_apart(sessions: sessionmaker[Session]) -> None:
    record(sessions, SMOKE_TEST_OPERATION, minutes_ago=3 * 24 * 60, target=None)
    record(
        sessions,
        SMOKE_TEST_OPERATION,
        minutes_ago=2 * 24 * 60,
        error_kind="extraction",
        target=None,
        duration_ms=5000,
    )

    result = status(sessions)

    assert result.operations == []
    assert result.recent_failures == []
    # The latest run, even outside the window.
    smoke = result.last_smoke_test
    assert smoke is not None
    assert (smoke.success, smoke.error, smoke.duration_ms) == (False, "extraction error", 5000)
    assert smoke.at == NOW - timedelta(days=2)


def test_hours_are_bounded(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(ValueError):
        status(sessions, hours=0)
    with pytest.raises(ValueError):
        status(sessions, hours=24 * 31)
