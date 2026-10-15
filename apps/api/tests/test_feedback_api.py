from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app
from homefeed_core import feeds
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory

CHANNEL = "UC" + "f" * 22
VIDEO_ID = "dQw4w9WgXcQ"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    with TestClient(app) as client:
        with get_session_factory().begin() as session:
            session.execute(
                text("INSERT INTO channels (id, title) VALUES (:id, 'Channel')"), {"id": CHANNEL}
            )
            session.execute(
                text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :channel, 'Video')"),
                {"id": VIDEO_ID, "channel": CHANNEL},
            )
        yield client
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def stored_feedback() -> list[tuple[str, int]]:
    with get_session_factory()() as session:
        rows = session.execute(text("SELECT video_id, signal FROM video_feedback")).all()
    return [(video_id, signal) for video_id, signal in rows]


def test_put_marks_a_video_more_like_this(client: TestClient) -> None:
    response = client.put(f"/videos/{VIDEO_ID}/feedback", json={"signal": 1})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["video_id"] == VIDEO_ID
    assert body["signal"] == 1 and isinstance(body["signal"], int)
    assert body["created_at"] == body["updated_at"]
    assert stored_feedback() == [(VIDEO_ID, 1)]


def test_put_replaces_the_earlier_signal(client: TestClient) -> None:
    created = client.put(f"/videos/{VIDEO_ID}/feedback", json={"signal": 1}).json()

    response = client.put(f"/videos/{VIDEO_ID}/feedback", json={"signal": -1})

    assert response.status_code == 200
    body = response.json()
    assert body["signal"] == -1
    assert body["created_at"] == created["created_at"]
    assert stored_feedback() == [(VIDEO_ID, -1)]


def test_putting_the_same_signal_again_changes_nothing(client: TestClient) -> None:
    created = client.put(f"/videos/{VIDEO_ID}/feedback", json={"signal": 1}).json()

    again = client.put(f"/videos/{VIDEO_ID}/feedback", json={"signal": 1})

    assert again.status_code == 200
    assert again.json() == created


def test_put_is_404_for_a_video_that_is_not_stored(client: TestClient) -> None:
    response = client.put("/videos/zzzzzzzzzzz/feedback", json={"signal": 1})

    assert response.status_code == 404
    assert response.json() == {"detail": "Video not found"}
    assert stored_feedback() == []


@pytest.mark.parametrize(
    "body",
    [{"signal": 0}, {"signal": 2}, {"signal": "1"}, {"signal": True}, {"signal": None}, {}],
)
def test_put_rejects_anything_but_more_or_less(client: TestClient, body: dict[str, object]) -> None:
    response = client.put(f"/videos/{VIDEO_ID}/feedback", json=body)

    assert response.status_code == 422
    assert stored_feedback() == []


def test_put_rejects_a_bad_video_id(client: TestClient) -> None:
    assert client.put("/videos/short/feedback", json={"signal": 1}).status_code == 422


def test_delete_takes_the_feedback_off(client: TestClient) -> None:
    client.put(f"/videos/{VIDEO_ID}/feedback", json={"signal": -1})

    response = client.delete(f"/videos/{VIDEO_ID}/feedback")

    assert response.status_code == 204
    assert response.content == b""
    assert stored_feedback() == []


def test_delete_is_404_without_feedback(client: TestClient) -> None:
    response = client.delete(f"/videos/{VIDEO_ID}/feedback")

    assert response.status_code == 404
    assert response.json() == {"detail": "Feedback not found"}
    assert client.delete("/videos/short/feedback").status_code == 422


def test_feedback_is_not_a_rating(client: TestClient) -> None:
    client.put(f"/videos/{VIDEO_ID}/feedback", json={"signal": 1})

    assert client.get(f"/ratings/{VIDEO_ID}").status_code == 404
    weeks = client.get("/insights/weekly").json()["weeks"]
    assert sum(week["rated_count"] for week in weeks) == 0
    with get_session_factory()() as session:
        assert feeds.load_history(session).n_ratings == 0


def test_a_rating_can_be_given_to_a_video_with_feedback(client: TestClient) -> None:
    client.put(f"/videos/{VIDEO_ID}/feedback", json={"signal": 1})

    rated = client.put(f"/ratings/{VIDEO_ID}", json={"score": 3})

    assert rated.status_code == 200
    # The two are separate: the rating doesn't touch the feedback.
    assert stored_feedback() == [(VIDEO_ID, 1)]


def test_the_endpoints_are_in_the_openapi_schema(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]

    assert paths["/videos/{video_id}/feedback"]["put"]["operationId"] == "set_video_feedback"
    assert paths["/videos/{video_id}/feedback"]["delete"]["operationId"] == "clear_video_feedback"
    assert paths["/feed-items/{item_id}/dismiss"]["delete"]["operationId"] == "undismiss_feed_item"
