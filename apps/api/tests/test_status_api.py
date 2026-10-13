from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from homefeed_api.main import app
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.extractor_status import SMOKE_TEST_OPERATION
from homefeed_core.gateway import ExtractorEvent, SqlEventRecorder


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    with TestClient(app) as client:
        yield client
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def record(
    operation: str, *, ago: timedelta, error_kind: str | None = None, target: str | None = "t"
) -> None:
    SqlEventRecorder(get_session_factory()).record(
        ExtractorEvent(
            operation=operation,
            target=target,
            success=error_kind is None,
            at=datetime.now(UTC) - ago,
            duration_ms=120,
            error_kind=error_kind,
            error="boom" if error_kind else None,
        )
    )


def test_status_without_events(client: TestClient) -> None:
    response = client.get("/status/extractors")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["hours"] == 24
    assert body["health"] == "unknown"
    assert body["operations"] == []
    assert body["recent_failures"] == []
    assert body["last_smoke_test"] is None


def test_status_aggregates_events(client: TestClient) -> None:
    record("get_video", ago=timedelta(minutes=30))
    record("get_video", ago=timedelta(minutes=20), error_kind="unavailable")
    for minutes in (15, 10, 5):
        record("get_related", ago=timedelta(minutes=minutes), error_kind="extraction")
    record("search", ago=timedelta(hours=30))  # outside the default window
    record(SMOKE_TEST_OPERATION, ago=timedelta(hours=2), error_kind="extraction", target=None)

    body = client.get("/status/extractors").json()

    assert body["health"] == "failing"
    ops = {op["operation"]: op for op in body["operations"]}
    assert set(ops) == {"get_video", "get_related"}
    assert ops["get_video"]["health"] == "ok"
    assert (ops["get_video"]["total"], ops["get_video"]["failures"]) == (2, 1)
    assert ops["get_video"]["breakage_failures"] == 0
    assert ops["get_video"]["success_rate"] == 0.5
    assert ops["get_video"]["avg_duration_ms"] == 120
    assert ops["get_related"]["health"] == "failing"
    assert ops["get_related"]["last_error_kind"] == "extraction"
    failures = body["recent_failures"]
    assert [(f["operation"], f["breakage"]) for f in failures] == [
        ("get_related", True),
        ("get_related", True),
        ("get_related", True),
        ("get_video", False),
    ]
    assert body["last_smoke_test"]["success"] is False
    assert body["last_smoke_test"]["error"] == "boom"

    wider = client.get("/status/extractors", params={"hours": 48}).json()
    assert {op["operation"] for op in wider["operations"]} == {
        "get_video",
        "get_related",
        "search",
    }


@pytest.mark.parametrize("hours", [0, 24 * 31])
def test_status_rejects_bad_windows(client: TestClient, hours: int) -> None:
    assert client.get("/status/extractors", params={"hours": hours}).status_code == 422
