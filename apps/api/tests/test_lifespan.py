import pytest
from fastapi.testclient import TestClient

from homefeed_api import main
from homefeed_core.config import get_settings


class FakeScheduler:
    def __init__(self) -> None:
        self.shutdown_calls: list[bool] = []

    def shutdown(self, wait: bool = True) -> None:
        self.shutdown_calls.append(wait)


@pytest.fixture
def fake_scheduler(monkeypatch: pytest.MonkeyPatch) -> FakeScheduler:
    fake = FakeScheduler()
    starts: list[None] = []

    def start() -> FakeScheduler:
        starts.append(None)
        return fake

    monkeypatch.setattr(main, "start_background_scheduler", start)
    fake.starts = starts  # type: ignore[attr-defined]
    return fake


def test_lifespan_starts_and_stops_the_scheduler_when_enabled(
    monkeypatch: pytest.MonkeyPatch, fake_scheduler: FakeScheduler
) -> None:
    monkeypatch.setenv("RUN_WORKER_IN_API", "true")
    get_settings.cache_clear()
    try:
        with TestClient(main.app):
            assert len(fake_scheduler.starts) == 1  # type: ignore[attr-defined]
            assert fake_scheduler.shutdown_calls == []
        assert fake_scheduler.shutdown_calls == [False]
    finally:
        get_settings.cache_clear()


def test_lifespan_leaves_the_scheduler_off_by_default(
    monkeypatch: pytest.MonkeyPatch, fake_scheduler: FakeScheduler
) -> None:
    monkeypatch.delenv("RUN_WORKER_IN_API", raising=False)
    get_settings.cache_clear()
    try:
        with TestClient(main.app):
            pass
    finally:
        get_settings.cache_clear()

    assert fake_scheduler.starts == []  # type: ignore[attr-defined]
    assert fake_scheduler.shutdown_calls == []
