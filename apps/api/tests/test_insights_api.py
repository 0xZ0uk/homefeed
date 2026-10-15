import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_api.main import app
from homefeed_core import feeds
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.insights import week_start
from homefeed_core.tags import ProposedTag, set_llm_tags

CHANNEL = "UC" + "c" * 22


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


def test_weekly_insights_without_data(client: TestClient) -> None:
    response = client.get("/insights/weekly", params={"weeks": 3})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["good_threshold"] == 6
    starts = [week["week_start"] for week in body["weeks"]]
    this_week = week_start(feeds.local_today())
    assert starts == [(this_week - timedelta(weeks=n)).isoformat() for n in (2, 1, 0)]
    assert body["weeks"][-1] == {
        "week_start": this_week.isoformat(),
        "rated_count": 0,
        "good_count": 0,
        "good_rate": None,
        "score_counts": [{"score": score, "count": 0} for score in range(10, 0, -1)],
        "shown_count": 0,
        "shown_rated_count": 0,
        "rating_rate": None,
        "feed_count": 0,
        "model_feed_count": 0,
        "score_share": None,
    }


def test_weekly_insights_defaults_to_twelve_weeks(client: TestClient) -> None:
    response = client.get("/insights/weekly")

    assert response.status_code == 200
    assert len(response.json()["weeks"]) == 12


@pytest.mark.parametrize("weeks", [0, 105])
def test_weekly_insights_rejects_out_of_range_weeks(client: TestClient, weeks: int) -> None:
    assert client.get("/insights/weekly", params={"weeks": weeks}).status_code == 422


def test_weekly_insights_this_week(client: TestClient) -> None:
    breakdown = {"model": 0.5, "alpha": 0.5, "channel": 0.25, "similarity": 0.0, "tags": {}}
    with get_session_factory().begin() as session:
        session.execute(text("INSERT INTO channels (id, title) VALUES (:id, 'C')"), {"id": CHANNEL})
        feed_id = session.execute(
            text("INSERT INTO feeds (date, model_version) VALUES (:d, '1') RETURNING id"),
            {"d": feeds.local_today().isoformat()},
        ).scalar_one()
        for n in range(2):
            video_id = f"v{n:010d}"
            session.execute(
                text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :c, 'V')"),
                {"id": video_id, "c": CHANNEL},
            )
            session.execute(
                text(
                    """
                    INSERT INTO feed_items (feed_id, video_id, position, source, score,
                                            breakdown, explanation)
                    VALUES (:f, :v, :p, 'subscription', 0.5, :b, '')
                    """
                ),
                {"f": feed_id, "v": video_id, "p": n, "b": json.dumps(breakdown)},
            )
    assert client.put("/ratings/v0000000000", json={"score": 6}).status_code == 200
    assert client.put("/ratings/x0000000000", json={"score": 5}).status_code == 200

    week = client.get("/insights/weekly", params={"weeks": 1}).json()["weeks"][0]

    assert (week["rated_count"], week["good_count"], week["good_rate"]) == (2, 1, 0.5)
    assert {c["score"]: c["count"] for c in week["score_counts"]}[6] == 1
    assert (week["shown_count"], week["shown_rated_count"], week["rating_rate"]) == (2, 1, 0.5)
    assert (week["feed_count"], week["model_feed_count"]) == (1, 1)
    assert week["score_share"] == {"model": 0.5, "curation": 0.5, "similarity": 0.0}


def channel_id(letter: str) -> str:
    return "UC" + letter * 22


def video_id(letter: str, n: int = 0) -> str:
    return f"{letter}{n:010d}"


def add_video(session: Session, letter: str, n: int, title: str) -> str:
    """A stored video of a channel (made if need be, titled `title`); returns its id."""
    session.execute(
        text("INSERT OR IGNORE INTO channels (id, title) VALUES (:id, :title)"),
        {"id": channel_id(letter), "title": title},
    )
    session.execute(
        text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :channel, 'V')"),
        {"id": video_id(letter, n), "channel": channel_id(letter)},
    )
    return video_id(letter, n)


def play(session: Session, video: str, days_ago: int = 0) -> None:
    at = datetime.now(UTC) - timedelta(days=days_ago)
    session.execute(
        text(
            "INSERT INTO watch_events (video_id, event_type, position, duration, at) "
            "VALUES (:video, 'play', 5, 600, :at)"
        ),
        {"video": video, "at": format_timestamp(at)},
    )


def test_discovery_recap_without_data(client: TestClient) -> None:
    response = client.get("/insights/discoveries")

    assert response.status_code == 200, response.text
    body = response.json()
    today = feeds.local_today()
    assert body["days"] == 7
    assert body["top_tier_threshold"] == 7
    assert body["current"] == {
        "start": (today - timedelta(days=6)).isoformat(),
        "end": today.isoformat(),
        "new_channels": 0,
        "kept_channels": 0,
        "liked_channels": 0,
        "videos_watched": 0,
        "new_channel_videos": 0,
        "new_channel_share": None,
        "new_topics": 0,
    }
    assert body["previous"]["start"] == (today - timedelta(days=13)).isoformat()
    assert body["previous"]["end"] == (today - timedelta(days=7)).isoformat()
    assert body["channels"] == []
    assert body["topics"] == []


def test_discovery_recap_days_sets_the_length_of_both_windows(client: TestClient) -> None:
    body = client.get("/insights/discoveries", params={"days": 3}).json()

    today = feeds.local_today()
    assert body["days"] == 3
    assert (body["current"]["start"], body["current"]["end"]) == (
        (today - timedelta(days=2)).isoformat(),
        today.isoformat(),
    )
    assert (body["previous"]["start"], body["previous"]["end"]) == (
        (today - timedelta(days=5)).isoformat(),
        (today - timedelta(days=3)).isoformat(),
    )


@pytest.mark.parametrize("days", [0, 91])
def test_discovery_recap_rejects_out_of_range_days(client: TestClient, days: int) -> None:
    assert client.get("/insights/discoveries", params={"days": days}).status_code == 422


def test_discovery_recap_days_are_in_the_user_time_zone(client: TestClient) -> None:
    zone = ZoneInfo("Pacific/Kiritimati")  # UTC+14
    assert (
        client.patch("/settings", json={"set": {"timezone": "Pacific/Kiritimati"}}).status_code
        == 200
    )

    body = client.get("/insights/discoveries").json()

    assert body["current"]["end"] == feeds.local_today(tz=zone).isoformat()


def test_discovery_recap_this_week_against_last(client: TestClient) -> None:
    with get_session_factory().begin() as session:
        # New this week: two videos of Woodworking (one rated 9), one of Birds, one of
        # Metalworking (rated 7).
        wood = [add_video(session, "a", n, "Woodworking") for n in range(2)]
        birds = add_video(session, "b", 0, "Birds")
        metal = add_video(session, "c", 0, "Metalworking")
        for video in (*wood, birds, metal):
            play(session, video)
        # Watched before as well, so this week's video isn't a first.
        old_friend = [add_video(session, "d", n, "Old friend") for n in range(2)]
        play(session, old_friend[0], days_ago=20)
        play(session, old_friend[1])
        # New last week, and subscribed since.
        gardening = add_video(session, "e", 0, "Gardening")
        play(session, gardening, days_ago=10)
        session.execute(
            text("INSERT INTO channel_prefs (channel_id) VALUES (:id)"), {"id": channel_id("e")}
        )
        set_llm_tags(
            session,
            wood[0],
            [ProposedTag("Hand tools", 0.9), ProposedTag("Woodworking", 0.8)],
            prompt_version=1,
        )
        set_llm_tags(
            session,
            metal,
            [ProposedTag("Hand tools", 0.6), ProposedTag("Welding", 0.9)],
            prompt_version=1,
        )
    assert client.put(f"/ratings/{wood[0]}", json={"score": 9}).status_code == 200
    assert client.put(f"/ratings/{metal}", json={"score": 7}).status_code == 200
    assert client.post(f"/channels/{channel_id('c')}/trial").status_code == 201
    hidden = client.put(f"/channels/{channel_id('b')}/hide", json={"kind": "dismissed"})
    assert hidden.status_code == 200, hidden.text

    body = client.get("/insights/discoveries").json()

    assert body["current"] | {"start": None, "end": None} == {
        "start": None,
        "end": None,
        "new_channels": 3,
        "kept_channels": 1,  # Metalworking, on trial
        "liked_channels": 2,
        "videos_watched": 5,
        "new_channel_videos": 4,
        "new_channel_share": 0.8,
        "new_topics": 3,
    }
    assert body["previous"] | {"start": None, "end": None} == {
        "start": None,
        "end": None,
        "new_channels": 1,
        "kept_channels": 1,
        "liked_channels": 0,
        "videos_watched": 1,
        "new_channel_videos": 1,
        "new_channel_share": 1.0,
        "new_topics": 0,
    }
    # The best rated first, then the unrated.
    wood_row, metal_row, birds_row = body["channels"]
    assert wood_row == {
        "channel_id": channel_id("a"),
        "title": "Woodworking",
        "handle": None,
        "thumbnail_url": None,
        "videos_watched": 2,
        "rating_count": 1,
        "average_score": 9.0,
        "top_score": 9,
        "status": "not_followed",
        "trial_until": None,
        "hide_kind": None,
        "follow_up": True,
    }
    assert (metal_row["title"], metal_row["status"], metal_row["follow_up"]) == (
        "Metalworking",
        "trial",
        False,
    )
    trial_ends = datetime.fromisoformat(metal_row["trial_until"])
    assert 13.9 < (trial_ends - datetime.now(UTC)) / timedelta(days=1) < 14.1
    assert (birds_row["title"], birds_row["status"], birds_row["hide_kind"]) == (
        "Birds",
        "hidden",
        "dismissed",
    )
    assert (birds_row["average_score"], birds_row["follow_up"]) == (None, False)
    assert body["topics"] == [
        {"slug": "hand-tools", "label": "Hand tools", "videos": 2},
        {"slug": "welding", "label": "Welding", "videos": 1},
        {"slug": "woodworking", "label": "Woodworking", "videos": 1},
    ]


def test_discovery_recap_is_in_the_openapi_schema(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()

    operation = schema["paths"]["/insights/discoveries"]["get"]
    assert operation["operationId"] == "get_discovery_recap"
    days = next(p for p in operation["parameters"] if p["name"] == "days")
    assert (days["schema"]["minimum"], days["schema"]["maximum"]) == (1, 90)
    assert days["schema"]["default"] == 7
    channel = schema["components"]["schemas"]["DiscoveredChannelOut"]
    assert channel["properties"]["status"]["enum"] == [
        "subscribed",
        "trial",
        "hidden",
        "not_followed",
    ]
    assert channel["properties"]["follow_up"]["description"]
    window = schema["components"]["schemas"]["DiscoveryWindowOut"]
    assert all(prop["description"] for prop in window["properties"].values())
