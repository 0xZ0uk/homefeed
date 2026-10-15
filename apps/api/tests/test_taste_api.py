from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.tags import add_manual_tag
from homefeed_core.trainer import MIN_EXPLICIT_RATINGS

WOOD = "UC" + "w" * 22
SMITH = "UC" + "s" * 22
LOOM = "UC" + "l" * 22


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


def video_id(channel_id: str, n: int) -> str:
    return f"{channel_id[-4:]}{n:07d}"


def seed() -> None:
    """Woodworking is followed; Smithing and Loom are known, not followed. Woodworking has
    five videos (tagged Godot, the first also Rust), picked in feeds built now, two a
    long while ago; Smithing has two."""
    now = datetime.now(UTC)
    with get_session_factory().begin() as session:
        for channel_id, title in ((WOOD, "Woodworking"), (SMITH, "Smithing"), (LOOM, "Loom")):
            session.execute(
                text("INSERT INTO channels (id, title, handle) VALUES (:id, :title, :handle)"),
                {"id": channel_id, "title": title, "handle": f"@{title.lower()}"},
            )
        session.execute(
            text("INSERT INTO channel_prefs (channel_id, prior) VALUES (:id, 'love')"),
            {"id": WOOD},
        )
        for channel_id in (WOOD, SMITH):
            for n in range(5 if channel_id == WOOD else 2):
                session.execute(
                    text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :channel, 'v')"),
                    {"id": video_id(channel_id, n), "channel": channel_id},
                )
        for n in range(5):
            add_manual_tag(session, video_id(WOOD, n), "Godot")
        add_manual_tag(session, video_id(WOOD, 0), "Rust")
        for created_at, videos in (
            (now - timedelta(days=60), [video_id(WOOD, 4)]),
            (now - timedelta(days=2), [video_id(WOOD, n) for n in range(4)]),
        ):
            feed_id = session.execute(
                text(
                    "INSERT INTO feeds (date, created_at) VALUES ('2026-10-12', :at) RETURNING id"
                ),
                {"at": format_timestamp(created_at)},
            ).scalar_one()
            for position, video in enumerate(videos):
                session.execute(
                    text(
                        "INSERT INTO feed_items (feed_id, video_id, position, source, score, "
                        "breakdown, explanation) VALUES (:feed, :video, :position, "
                        "'subscription', 0.5, '{}', 'x')"
                    ),
                    {"feed": feed_id, "video": video, "position": position},
                )
        session.execute(
            text(
                "UPDATE feed_items SET dismissed_at = :at, dismiss_reason = 'Clickbait' "
                "WHERE video_id = :video"
            ),
            {"at": format_timestamp(now - timedelta(hours=12)), "video": video_id(WOOD, 3)},
        )


def test_a_fresh_install_has_nothing_to_report(client: TestClient) -> None:
    response = client.get("/taste")

    assert response.status_code == 200, response.text
    assert response.json() == {
        "days": 30,
        "total_picks": 0,
        "min_ratings_to_train": MIN_EXPLICIT_RATINGS,
        "tags": [],
        "channel_priors": {"love": 0, "like": 0, "neutral": 0, "skeptical": 0},
        "unfollowed_channels": [],
        "signals": {
            "ratings": 0,
            "watched": 0,
            "more_like_this": 0,
            "less_like_this": 0,
            "dismissals": [],
        },
    }


def test_topics_carry_their_picks_watching_and_ratings(client: TestClient) -> None:
    seed()
    assert client.post("/tags/godot/subscribe").status_code == 200
    assert client.patch("/tags/godot/subscription", json={"weight": 0.9}).status_code == 200
    assert client.post("/tags/rust/mute").status_code == 200
    assert client.put(f"/ratings/{video_id(WOOD, 0)}", json={"score": 9}).status_code == 200
    assert client.put(f"/ratings/{video_id(WOOD, 4)}", json={"score": 6}).status_code == 200
    play = {"video_id": video_id(WOOD, 1), "event_type": "play", "position": 3, "duration": 600}
    assert client.post("/watch-events", json=play).status_code == 201

    body = client.get("/taste").json()

    assert body["total_picks"] == 4  # the two-month-old feed is outside the window
    godot, rust = body["tags"]
    assert godot == {
        "tag_id": godot["tag_id"],
        "slug": "godot",
        "label": "Godot",
        "weight": 0.9,
        "hide": False,
        "picks": 4,
        "watched_picks": 2,  # one rated, one played
        "rating_count": 2,  # the rated video that was picked a while ago counts too
        "average_score": 7.5,
    }
    assert (rust["slug"], rust["weight"], rust["picks"]) == ("rust", -0.5, 1)
    assert (rust["rating_count"], rust["average_score"]) == (1, 9.0)


def test_channels_by_preference_and_the_well_rated_unfollowed(client: TestClient) -> None:
    seed()
    for n, score in enumerate([9, 8]):
        assert (
            client.put(f"/ratings/{video_id(SMITH, n)}", json={"score": score}).status_code == 200
        )
    assert client.put(f"/ratings/{video_id(WOOD, 0)}", json={"score": 10}).status_code == 200

    body = client.get("/taste").json()

    assert body["channel_priors"] == {"love": 1, "like": 0, "neutral": 0, "skeptical": 0}
    assert body["unfollowed_channels"] == [
        {
            "channel_id": SMITH,
            "title": "Smithing",
            "handle": "@smithing",
            "thumbnail_url": None,
            "rating_count": 2,
            "average_score": 8.5,
        }
    ]


def test_signals_count_ratings_feedback_and_dismissals(client: TestClient) -> None:
    seed()
    assert client.put(f"/ratings/{video_id(WOOD, 0)}", json={"score": 8}).status_code == 200
    play = {"video_id": video_id(WOOD, 1), "event_type": "play", "position": 3, "duration": 600}
    assert client.post("/watch-events", json=play).status_code == 201
    for n, signal in enumerate([1, 1, -1]):
        response = client.put(f"/videos/{video_id(WOOD, n)}/feedback", json={"signal": signal})
        assert response.status_code == 200

    signals = client.get("/taste").json()["signals"]

    assert signals == {
        "ratings": 1,
        "watched": 2,
        "more_like_this": 2,
        "less_like_this": 1,
        "dismissals": [{"reason": "Clickbait", "count": 1}],
    }


def test_the_window_is_a_query_parameter(client: TestClient) -> None:
    seed()
    client.post("/tags/godot/subscribe")

    narrow = client.get("/taste", params={"days": 1}).json()
    wide = client.get("/taste", params={"days": 90}).json()

    assert (narrow["days"], narrow["total_picks"], narrow["tags"][0]["picks"]) == (1, 0, 0)
    assert narrow["signals"]["dismissals"] == [{"reason": "Clickbait", "count": 1}]
    assert (wide["days"], wide["total_picks"], wide["tags"][0]["picks"]) == (90, 5, 5)


@pytest.mark.parametrize("days", [0, -3, 366])
def test_a_window_out_of_range_is_refused(client: TestClient, days: int) -> None:
    assert client.get("/taste", params={"days": days}).status_code == 422
