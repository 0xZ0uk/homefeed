from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from homefeed_api.main import app, get_gateway, get_playback
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway import ExtractionError, Video
from homefeed_core.gateway.events import ExtractorEvent, SqlEventRecorder
from homefeed_core.gateway.fake import FakeGateway, make_channel, make_video
from homefeed_core.playback import Playback
from homefeed_core.videos import get_stored_video

CHANNEL = make_channel("UC" + "w" * 22, title="Woodworking")
A, B, C = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"


@pytest.fixture
def gateway() -> FakeGateway:
    gateway = FakeGateway()
    for video_id, title in [(A, "Planing"), (B, "Sawing"), (C, "Gluing")]:
        gateway.add_video(make_video(video_id, channel=CHANNEL, title=title))
    return gateway


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gateway: FakeGateway
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    playback = Playback(gateway)
    app.dependency_overrides[get_gateway] = lambda: gateway
    app.dependency_overrides[get_playback] = lambda: playback
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def enqueue(client: TestClient, video_id: str, **body: Any) -> dict[str, Any]:
    response = client.post("/queue", json={"video_id": video_id, **body})
    assert response.status_code == 201, response.text
    return response.json()


def order(client: TestClient) -> list[str]:
    response = client.get("/queue")
    assert response.status_code == 200
    items = response.json()
    assert [item["position"] for item in items] == list(range(len(items)))
    return [item["video_id"] for item in items]


def test_empty_queue(client: TestClient) -> None:
    assert client.get("/queue").json() == []


def test_add_fetches_and_stores_metadata(client: TestClient) -> None:
    item = enqueue(client, A)

    assert item == {
        "id": item["id"],
        "video_id": A,
        "position": 0,
        "added_at": item["added_at"],
        "title": "Planing",
        "channel_id": CHANNEL.id,
        "channel_title": "Woodworking",
        "duration_seconds": 600,
        "published_at": "2026-01-01T00:00:00.000Z",
        "thumbnail_url": None,
    }
    assert client.get("/queue").json() == [item]
    with get_session_factory()() as session:
        assert get_stored_video(session, A) is not None


def test_add_uses_stored_metadata_without_youtube(client: TestClient, gateway: FakeGateway) -> None:
    assert client.get(f"/videos/{A}").status_code == 200  # stores it
    gateway.fail("get_video", A, ExtractionError("network down"))

    assert enqueue(client, A)["title"] == "Planing"


def test_add_at_position(client: TestClient) -> None:
    enqueue(client, A)
    enqueue(client, B)
    assert enqueue(client, C, position=0)["position"] == 0

    assert order(client) == [C, A, B]


def test_adding_again_returns_200_with_the_existing_item(client: TestClient) -> None:
    a = enqueue(client, A)
    enqueue(client, B)

    response = client.post("/queue", json={"video_id": A, "position": 1})

    assert response.status_code == 200
    assert response.json() == a
    assert order(client) == [A, B]


def test_add_unknown_video_is_404(client: TestClient) -> None:
    response = client.post("/queue", json={"video_id": "zzzzzzzzzzz"})

    assert response.status_code == 404
    assert order(client) == []


def test_add_when_youtube_is_down_is_502(client: TestClient, gateway: FakeGateway) -> None:
    gateway.fail("get_video", A, ExtractionError("network down"))

    assert client.post("/queue", json={"video_id": A}).status_code == 502
    assert order(client) == []


@pytest.mark.parametrize(
    "body",
    [{"video_id": "short"}, {"video_id": A, "position": -1}, {}],
)
def test_add_validates_input(client: TestClient, body: dict[str, Any]) -> None:
    assert client.post("/queue", json=body).status_code == 422


def test_move_returns_the_new_order(client: TestClient) -> None:
    a = enqueue(client, A)
    enqueue(client, B)
    enqueue(client, C)

    response = client.patch(f"/queue/{a['id']}", json={"position": 2})

    assert response.status_code == 200
    assert [item["video_id"] for item in response.json()] == [B, C, A]
    assert order(client) == [B, C, A]
    response = client.patch(f"/queue/{a['id']}", json={"position": 0})
    assert order(client) == [A, B, C]


def test_move_past_the_end_moves_last(client: TestClient) -> None:
    a = enqueue(client, A)
    enqueue(client, B)

    assert client.patch(f"/queue/{a['id']}", json={"position": 10}).status_code == 200
    assert order(client) == [B, A]


def test_move_unknown_item_is_404(client: TestClient) -> None:
    response = client.patch("/queue/99", json={"position": 0})
    assert response.status_code == 404
    assert response.json() == {"detail": "Queue item not found"}


def test_remove(client: TestClient) -> None:
    enqueue(client, A)
    b = enqueue(client, B)
    enqueue(client, C)

    assert client.delete(f"/queue/{b['id']}").status_code == 204
    assert order(client) == [A, C]
    assert client.delete(f"/queue/{b['id']}").status_code == 404


def test_clear(client: TestClient) -> None:
    enqueue(client, A)
    enqueue(client, B)

    assert client.delete("/queue").status_code == 204
    assert order(client) == []


def test_watching_to_the_end_removes_from_queue(client: TestClient) -> None:
    enqueue(client, A)
    enqueue(client, B)

    for event_type in ("play", "pause", "close"):
        body = {"video_id": A, "event_type": event_type, "position": 10}
        assert client.post("/watch-events", json=body).status_code == 201
    assert order(client) == [A, B]

    body = {"video_id": A, "event_type": "ended", "position": 600}
    assert client.post("/watch-events", json=body).status_code == 201
    assert order(client) == [B]


def test_queueing_an_unstored_video_survives_a_commit_during_the_fetch(
    client: TestClient, gateway: FakeGateway
) -> None:
    # Like the real Gateway, record an extractor event (a commit) while fetching.
    fetch = gateway.get_video
    recorder = SqlEventRecorder(get_session_factory())

    def get_video(video_id: str) -> Video:
        recorder.record(ExtractorEvent("get_video", video_id, True, datetime.now(UTC)))
        return fetch(video_id)

    gateway.get_video = get_video  # type: ignore[method-assign]

    enqueue(client, A)

    assert order(client) == [A]
