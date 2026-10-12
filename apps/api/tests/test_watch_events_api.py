from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from homefeed_api.main import app
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.feeds import watched_video_ids
from homefeed_core.watch_events import abandoned_early, list_watch_events

VIDEO_ID = "dQw4w9WgXcQ"


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


def post(client: TestClient, **body: Any) -> Any:
    return client.post("/watch-events", json={"video_id": VIDEO_ID, **body})


def test_records_event(client: TestClient) -> None:
    response = post(client, event_type="pause", position=42.5, duration=300)

    assert response.status_code == 201
    body = response.json()
    assert body["video_id"] == VIDEO_ID
    assert body["event_type"] == "pause"
    assert body["position"] == 42.5
    assert body["duration"] == 300
    assert body["at"].endswith("Z")
    assert isinstance(body["id"], int)
    with get_session_factory()() as session:
        [event] = list_watch_events(session, VIDEO_ID)
    assert event.id == body["id"]


def test_duration_is_optional(client: TestClient) -> None:
    response = post(client, event_type="close", position=0)
    assert response.status_code == 201
    assert response.json()["duration"] is None


def test_play_marks_watched_and_short_visit_is_abandoned(client: TestClient) -> None:
    assert post(client, event_type="play", position=0, duration=600).status_code == 201
    assert post(client, event_type="close", position=25, duration=600).status_code == 201

    with get_session_factory()() as session:
        assert VIDEO_ID in watched_video_ids(session)
        assert abandoned_early(session, VIDEO_ID)


@pytest.mark.parametrize(
    "body",
    [
        {"event_type": "timeupdate", "position": 1},
        {"event_type": "play"},
        {"event_type": "play", "position": -1},
        {"event_type": "play", "position": 1, "duration": 0},
        {"event_type": "play", "position": 1, "video_id": "short"},
        {"position": 1},
    ],
)
def test_rejects_invalid_events(client: TestClient, body: dict[str, Any]) -> None:
    assert post(client, **body).status_code == 422
    with get_session_factory()() as session:
        assert list_watch_events(session, VIDEO_ID) == []
