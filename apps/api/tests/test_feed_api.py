import random
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app, get_feed_poll, get_gateway
from homefeed_core import feeds
from homefeed_core.candidates import SUBSCRIPTION, record
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway.fake import FakeGateway

WOOD = "UC" + "w" * 22
BIRDS = "UC" + "b" * 22
YESTERDAY = feeds.local_today() - timedelta(days=1)


class PollRecorder:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    def __call__(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


@pytest.fixture
def poll() -> PollRecorder:
    return PollRecorder()


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, poll: PollRecorder
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    # A purely score-ordered feed; test_refresh_with_exploration_slots turns them on.
    monkeypatch.setenv("FEED_EXPLORATION_SLOTS", "0")
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    app.dependency_overrides[get_gateway] = FakeGateway
    app.dependency_overrides[get_feed_poll] = lambda: poll
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def seed() -> None:
    """Two subscribed channels with two recent uploads each; one has no duration (RSS)."""
    now = datetime.now(UTC)
    with get_session_factory().begin() as session:
        for channel_id, title, prior in [(WOOD, "Woodworking", "love"), (BIRDS, "Birds", None)]:
            session.execute(
                text("INSERT INTO channels (id, title, handle) VALUES (:id, :title, NULL)"),
                {"id": channel_id, "title": title},
            )
            session.execute(
                text("INSERT INTO channel_prefs (channel_id, prior) VALUES (:id, :prior)"),
                {"id": channel_id, "prior": prior or "neutral"},
            )
            for n in range(2):
                video_id = f"{channel_id[2]}{n:010d}"
                session.execute(
                    text(
                        """
                        INSERT INTO videos (id, channel_id, title, published_at,
                                            duration_seconds, view_count, thumbnail_url)
                        VALUES (:id, :channel, :title, :published, :duration, :views, :thumb)
                        """
                    ),
                    {
                        "id": video_id,
                        "channel": channel_id,
                        "title": f"{title} {n}",
                        "published": (now - timedelta(hours=n + 1)).isoformat(),
                        "duration": None if n else 600,
                        "views": None if n else 1234,
                        "thumb": None if n else f"https://example.invalid/{video_id}.jpg",
                    },
                )
                record(session, [video_id], source=SUBSCRIPTION, source_detail=channel_id)


def build(feed_date: date) -> feeds.Feed:
    with get_session_factory().begin() as session:
        return feeds.build_feed(session, feed_date=feed_date, rng=random.Random(0))


def test_today_is_404_before_any_feed(client: TestClient) -> None:
    response = client.get("/feed/today")

    assert response.status_code == 404
    assert response.json() == {"detail": f"No feed for {feeds.local_today().isoformat()}"}


def test_feeds_is_empty_before_any_feed(client: TestClient) -> None:
    response = client.get("/feeds")

    assert response.status_code == 200
    assert response.json() == []


def test_refresh_polls_then_builds_todays_feed(client: TestClient, poll: PollRecorder) -> None:
    seed()

    response = client.post("/feed/refresh")

    assert response.status_code == 200, response.text
    body = response.json()
    assert poll.calls == 1
    assert body["date"] == feeds.local_today().isoformat()
    assert body["model_version"] is None
    assert [item["position"] for item in body["items"]] == [0, 1, 2, 3]
    first = body["items"][0]
    assert first["channel_id"] == WOOD  # the loved channel ranks first
    assert first == {
        "id": first["id"],
        "position": 0,
        "video_id": first["video_id"],
        "title": first["title"],
        "description": None,
        "duration_seconds": first["duration_seconds"],
        "published_at": first["published_at"],
        "thumbnail_url": first["thumbnail_url"],
        "view_count": first["view_count"],
        "channel_id": WOOD,
        "channel_title": "Woodworking",
        "channel_handle": None,
        "channel_thumbnail_url": None,
        "source": "subscription",
        "source_detail": WOOD,
        "score": first["score"],
        "breakdown": {
            "model": 0.0,
            "alpha": 0.0,
            "channel": first["breakdown"]["channel"],
            "similarity": 0.0,
            "topics": {},
            "final": first["score"],
            "similarity_features": None,
        },
        "explanation": "New from your subscriptions · channel you love",
        "is_pinned": False,
        "is_exploration": False,
        "selection_probability": None,
        "dismissed_at": None,
        "dismiss_reason": None,
        "watched": False,
    }
    durations = {item["video_id"]: item["duration_seconds"] for item in body["items"]}
    assert durations["w0000000000"] == 600
    assert durations["w0000000001"] is None  # RSS-only videos have no duration


def test_refresh_with_exploration_slots(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FEED_EXPLORATION_SLOTS", "1")
    get_settings.cache_clear()
    seed()

    response = client.post("/feed/refresh")

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    explored = [item for item in items if item["is_exploration"]]
    assert len(explored) == 1
    assert items[0] == explored[0]  # exploration comes before the top-scored items
    assert 0.0 < explored[0]["selection_probability"] <= 1.0
    assert explored[0]["explanation"].startswith("Exploring: new channel")
    assert all(item["selection_probability"] is None for item in items[1:])


def test_refresh_survives_a_failing_poll(client: TestClient, poll: PollRecorder) -> None:
    seed()
    poll.error = RuntimeError("network down")

    response = client.post("/feed/refresh")

    assert response.status_code == 200
    assert poll.calls == 1
    assert len(response.json()["items"]) == 4


def test_refresh_with_no_candidates_stores_an_empty_feed(client: TestClient) -> None:
    response = client.post("/feed/refresh")

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert client.get("/feed/today").json()["items"] == []


def test_today_returns_the_latest_refresh(client: TestClient) -> None:
    seed()
    first = client.post("/feed/refresh").json()
    second = client.post("/feed/refresh").json()

    response = client.get("/feed/today")

    assert response.status_code == 200
    assert second["id"] != first["id"]
    assert response.json() == second


def test_feed_by_date(client: TestClient) -> None:
    seed()
    past = build(YESTERDAY)

    response = client.get(f"/feed/{YESTERDAY.isoformat()}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == past.id
    assert body["date"] == YESTERDAY.isoformat()
    assert [item["video_id"] for item in body["items"]] == [i.video_id for i in past.items]


def test_feed_by_date_is_404_without_a_feed(client: TestClient) -> None:
    response = client.get("/feed/2020-01-01")

    assert response.status_code == 404
    assert response.json() == {"detail": "No feed for 2020-01-01"}


def test_feed_by_date_rejects_a_bad_date(client: TestClient) -> None:
    assert client.get("/feed/yesterday").status_code == 422
    assert client.get("/feed/2026-13-01").status_code == 422


def test_feeds_lists_the_latest_feed_per_date_newest_first(client: TestClient) -> None:
    seed()
    build(YESTERDAY)
    client.post("/feed/refresh")
    latest = client.post("/feed/refresh").json()

    response = client.get("/feeds")

    assert response.status_code == 200
    body = response.json()
    assert [(f["date"], f["item_count"]) for f in body] == [
        (feeds.local_today().isoformat(), 4),
        (YESTERDAY.isoformat(), 4),
    ]
    assert body[0]["id"] == latest["id"]
    assert set(body[0]) == {"id", "date", "created_at", "model_version", "item_count"}


def test_feeds_limit(client: TestClient) -> None:
    build(YESTERDAY)
    build(YESTERDAY - timedelta(days=1))

    body = client.get("/feeds", params={"limit": 1}).json()

    assert [f["date"] for f in body] == [YESTERDAY.isoformat()]
    assert client.get("/feeds", params={"limit": 0}).status_code == 422


def test_dismiss_sets_dismissed_at_and_reason(client: TestClient) -> None:
    seed()
    item = client.post("/feed/refresh").json()["items"][1]

    response = client.post(f"/feed-items/{item['id']}/dismiss", json={"reason": "Not interested"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["dismissed_at"] is not None
    assert body["dismiss_reason"] == "Not interested"
    assert body == {
        **item,
        "dismissed_at": body["dismissed_at"],
        "dismiss_reason": "Not interested",
    }
    today = client.get("/feed/today").json()["items"]
    assert [i["dismissed_at"] is not None for i in today] == [False, True, False, False]


def test_dismiss_without_a_reason(client: TestClient) -> None:
    seed()
    item = client.post("/feed/refresh").json()["items"][0]

    no_body = client.post(f"/feed-items/{item['id']}/dismiss")
    empty = client.post(f"/feed-items/{item['id']}/dismiss", json={})

    assert no_body.status_code == empty.status_code == 200
    assert no_body.json()["dismissed_at"] is not None
    assert no_body.json()["dismiss_reason"] is None
    assert empty.json() == no_body.json()


def test_dismissed_videos_are_left_out_of_later_feeds(client: TestClient) -> None:
    seed()
    item = client.post("/feed/refresh").json()["items"][0]
    client.post(f"/feed-items/{item['id']}/dismiss", json={"reason": "Seen it elsewhere"})

    refreshed = client.post("/feed/refresh").json()

    assert item["video_id"] not in {i["video_id"] for i in refreshed["items"]}
    assert len(refreshed["items"]) == 3


def test_dismiss_is_404_for_a_missing_item(client: TestClient) -> None:
    response = client.post("/feed-items/999/dismiss", json={"reason": "x"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Feed item not found"}


def test_dismiss_rejects_bad_input(client: TestClient) -> None:
    seed()
    item = client.post("/feed/refresh").json()["items"][0]

    too_long = client.post(f"/feed-items/{item['id']}/dismiss", json={"reason": "x" * 201})

    assert too_long.status_code == 422
    assert client.post("/feed-items/0/dismiss").status_code == 422
    assert client.post("/feed-items/abc/dismiss").status_code == 422
    assert client.get("/feed/today").json()["items"][0]["dismissed_at"] is None


def test_more_appends_new_picks_to_the_feed(client: TestClient) -> None:
    seed()
    feed = client.post("/feed/refresh").json()
    with get_session_factory().begin() as session:
        session.execute(
            text(
                "INSERT INTO videos (id, channel_id, title, published_at) "
                "VALUES ('fresh000001', :channel, 'Fresh', :published)"
            ),
            {"channel": WOOD, "published": datetime.now(UTC).isoformat()},
        )
        record(session, ["fresh000001"], source=SUBSCRIPTION, source_detail=WOOD)

    response = client.post(f"/feeds/{feed['id']}/more")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == feed["id"]
    assert [item["position"] for item in body["items"]] == [0, 1, 2, 3, 4]
    assert [item["video_id"] for item in body["items"][:4]] == [
        item["video_id"] for item in feed["items"]
    ]
    assert body["items"][4]["video_id"] == "fresh000001"
    assert client.get("/feed/today").json() == body


def test_more_returns_the_feed_unchanged_when_nothing_is_left(client: TestClient) -> None:
    seed()
    feed = client.post("/feed/refresh").json()

    response = client.post(f"/feeds/{feed['id']}/more")

    assert response.status_code == 200
    assert response.json() == feed


def test_more_is_404_for_a_missing_feed(client: TestClient) -> None:
    response = client.post("/feeds/999/more")

    assert response.status_code == 404
    assert response.json() == {"detail": "No such feed"}
    assert client.post("/feeds/0/more").status_code == 422
