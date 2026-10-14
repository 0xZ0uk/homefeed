from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from homefeed_api.main import app
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway import Video
from homefeed_core.videos import store_video

PLANE = "aaaaaaaaaaa"
BREAD = "bbbbbbbbbbb"


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


def store(video_id: str, title: str, channel_title: str) -> None:
    with get_session_factory().begin() as session:
        store_video(
            session,
            Video(
                id=video_id,
                title=title,
                channel_id=f"UC{video_id:_<22}",
                channel_title=channel_title,
                duration_seconds=600,
            ),
        )


def watch(client: TestClient, video_id: str, *events: tuple[str, float]) -> None:
    for event_type, position in events:
        response = client.post(
            "/watch-events",
            json={
                "video_id": video_id,
                "event_type": event_type,
                "position": position,
                "duration": 600,
            },
        )
        assert response.status_code == 201


@pytest.fixture
def watched(client: TestClient) -> None:
    store(PLANE, "Hand plane restoration", "Wood Shop")
    store(BREAD, "Sourdough basics", "Bread Lab")
    watch(client, PLANE, ("play", 0), ("pause", 125.5))
    watch(client, BREAD, ("play", 0), ("ended", 600))


def ids(response: Any) -> list[str]:
    assert response.status_code == 200
    return [entry["video_id"] for entry in response.json()]


@pytest.mark.usefixtures("watched")
def test_lists_history_newest_first(client: TestClient) -> None:
    response = client.get("/history")

    assert ids(response) == [BREAD, PLANE]
    bread, plane = response.json()
    assert plane["title"] == "Hand plane restoration"
    assert plane["channel_title"] == "Wood Shop"
    assert plane["position"] == 125.5
    assert plane["resume_position"] == 125.5
    assert plane["finished"] is False
    assert plane["last_watched_at"].endswith("Z")
    assert bread["finished"] is True
    assert bread["resume_position"] is None
    assert bread["score"] is None


@pytest.mark.usefixtures("watched")
def test_history_shows_the_whole_score_of_a_rated_video(client: TestClient) -> None:
    assert client.put(f"/ratings/{PLANE}", json={"score": 8}).status_code == 200

    [entry] = [e for e in client.get("/history").json() if e["video_id"] == PLANE]

    assert entry["score"] == 8 and isinstance(entry["score"], int)


@pytest.mark.usefixtures("watched")
def test_searches_history(client: TestClient) -> None:
    assert ids(client.get("/history", params={"q": "plane"})) == [PLANE]
    assert ids(client.get("/history", params={"q": "bread LAB"})) == [BREAD]
    assert ids(client.get("/history", params={"q": "nothing like it"})) == []
    assert ids(client.get("/history", params={"q": ""})) == [BREAD, PLANE]


@pytest.mark.usefixtures("watched")
def test_pages_history(client: TestClient) -> None:
    assert ids(client.get("/history", params={"limit": 1})) == [BREAD]
    assert ids(client.get("/history", params={"limit": 1, "offset": 1})) == [PLANE]
    assert ids(client.get("/history", params={"offset": 2})) == []


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 201}, {"offset": -1}, {"q": "x" * 201}])
def test_rejects_bad_params(client: TestClient, params: dict[str, Any]) -> None:
    assert client.get("/history", params=params).status_code == 422


@pytest.mark.usefixtures("watched")
def test_entry_has_resume_position(client: TestClient) -> None:
    response = client.get(f"/history/{PLANE}")
    assert response.status_code == 200
    assert response.json()["resume_position"] == 125.5

    # Leaving later saves the newer position.
    watch(client, PLANE, ("play", 125.5), ("close", 300))
    assert client.get(f"/history/{PLANE}").json()["resume_position"] == 300

    # A finished video starts over.
    assert client.get(f"/history/{BREAD}").json()["resume_position"] is None


def test_entry_404s_until_played(client: TestClient) -> None:
    assert client.get(f"/history/{PLANE}").status_code == 404
    watch(client, PLANE, ("close", 0))
    assert client.get(f"/history/{PLANE}").status_code == 404
    assert client.get("/history/short").status_code == 422
