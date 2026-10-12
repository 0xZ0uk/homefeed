import json
import random
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import feeds
from homefeed_core.candidates import SUBSCRIPTION, record
from homefeed_core.config import Settings
from homefeed_core.db import open_database
from homefeed_core.ratings import set_rating
from homefeed_core.watch_events import record_watch_event

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
TODAY = date(2026, 10, 12)
LOVED = "UC" + "l" * 22
PLAIN = "UC" + "p" * 22
MUTED = "UC" + "m" * 22
PINNED = "UC" + "x" * 22
GONE = "UC" + "g" * 22  # unsubscribed
SETTINGS = Settings(feed_size=15)


def vid(channel_id: str, n: int) -> str:
    return f"{channel_id[2]}{n:010d}"


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    with factory.begin() as session:
        for channel_id, prefs in [
            (LOVED, {"prior": "love"}),
            (PLAIN, {}),
            (MUTED, {"muted": 1}),
            (PINNED, {"pinned": 1}),
            (GONE, None),
        ]:
            session.execute(
                text("INSERT INTO channels (id, title, handle) VALUES (:id, :title, :handle)"),
                {"id": channel_id, "title": f"Channel {channel_id[2]}", "handle": "@h"},
            )
            if prefs is not None:
                session.execute(
                    text(
                        "INSERT INTO channel_prefs (channel_id, prior, pinned, muted) "
                        "VALUES (:id, :prior, :pinned, :muted)"
                    ),
                    {"id": channel_id, "prior": "neutral", "pinned": 0, "muted": 0, **prefs},
                )
            add_videos(session, channel_id, range(4))
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def add_videos(
    session: Session, channel_id: str, numbers: range, *, seen: datetime = NOW, **columns: object
) -> None:
    for n in numbers:
        session.execute(
            text(
                """
                INSERT INTO videos (id, channel_id, title, published_at, duration_seconds,
                                    live_status, is_short)
                VALUES (:id, :channel, :title, :published, :duration, :live, :short)
                """
            ),
            {
                "id": vid(channel_id, n),
                "channel": channel_id,
                "title": f"Video {n}",
                "published": f"2026-10-{n + 1:02d}T00:00:00.000Z",
                "duration": columns.get("duration"),
                "live": columns.get("live"),
                "short": columns.get("short", 0),
            },
        )
        record(
            session,
            [vid(channel_id, n)],
            source=SUBSCRIPTION,
            source_detail=channel_id,
            now=seen - timedelta(hours=1),
        )


def build(
    sessions: sessionmaker[Session], *, feed_date: date | None = None, settings: Settings = SETTINGS
) -> feeds.Feed:
    with sessions.begin() as session:
        return feeds.build_feed(
            session, feed_date=feed_date, settings=settings, rng=random.Random(0), now=NOW
        )


def test_build_feed_ranks_composes_and_stores(sessions: sessionmaker[Session]) -> None:
    feed = build(sessions, feed_date=TODAY)

    channels = [item.channel_id for item in feed.items]
    assert feed.date == TODAY and feed.model_version is None
    # Pins first, then the loved channel, at most 2 per channel; muted and unsubscribed out.
    assert channels == [PINNED, PINNED, LOVED, LOVED, PLAIN, PLAIN]
    assert [item.position for item in feed.items] == list(range(6))
    first = feed.items[0]
    assert first.is_pinned and not first.is_exploration
    assert first.video_id == vid(PINNED, 3)  # newest first among equal scores
    assert first.channel_title == "Channel x"
    assert first.title == "Video 3"
    assert feed.items[2].breakdown.channel == pytest.approx(0.8)
    assert feed.items[2].score == pytest.approx(feed.items[2].breakdown.final)
    assert feed.items[2].explanation == "New from your subscriptions · channel you love"

    with sessions() as session:
        stored = session.execute(text("SELECT breakdown FROM feed_items LIMIT 1")).scalar_one()
        assert set(json.loads(stored)) == {"model", "alpha", "channel", "topics", "final"}
        assert feeds.get_feed(session, TODAY) == feed


def test_feed_size_is_exact_with_enough_candidates(sessions: sessionmaker[Session]) -> None:
    feed = build(sessions, settings=Settings(feed_size=3))

    assert len(feed.items) == 3


def test_watched_and_dismissed_are_left_out(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_rating(session, vid(LOVED, 3), "B")
    first = build(sessions)
    with sessions.begin() as session:
        session.execute(
            text("UPDATE feed_items SET dismissed_at = 'x' WHERE video_id = :id"),
            {"id": vid(LOVED, 2)},
        )

    second = build(sessions)

    shown = {item.video_id for item in second.items}
    assert vid(LOVED, 3) not in {item.video_id for item in first.items}
    assert vid(LOVED, 2) in {item.video_id for item in first.items}
    assert {vid(LOVED, 3), vid(LOVED, 2)}.isdisjoint(shown)
    assert {vid(LOVED, 1), vid(LOVED, 0)} <= shown


def test_played_videos_are_left_out(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        record_watch_event(session, vid(LOVED, 3), "play", 0.0, 600.0)
        record_watch_event(session, vid(LOVED, 3), "close", 30.0, 600.0)
        # Opened but never played: still a candidate.
        record_watch_event(session, vid(LOVED, 2), "close", 0.0, 600.0)

    shown = {item.video_id for item in build(sessions).items}

    assert vid(LOVED, 3) not in shown
    assert vid(LOVED, 2) in shown


def test_ratings_shape_channel_score(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add_videos(session, PLAIN, range(10, 15))
        for n in range(10, 15):
            set_rating(session, vid(PLAIN, n), "S++")

    feed = build(sessions)

    plain = [item for item in feed.items if item.channel_id == PLAIN]
    assert plain[0].breakdown.channel == pytest.approx(5 / 10)
    assert plain[0].explanation.endswith("channel score +0.50 from 5 ratings")
    assert plain[0].breakdown.alpha == 0.0


def test_hard_filters_and_unknown_metadata(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        session.execute(text("DELETE FROM candidates"))
        add_videos(session, PLAIN, range(20, 21), short=1)
        add_videos(session, PLAIN, range(21, 22), live="is_upcoming")
        add_videos(session, PLAIN, range(22, 23), duration=30)
        add_videos(session, PLAIN, range(23, 24), duration=10_000)
        add_videos(session, LOVED, range(24, 25), duration=600)
        add_videos(session, LOVED, range(25, 26))  # duration and live status unknown

    feed = build(sessions, settings=Settings(feed_max_duration_seconds=3600))

    assert [item.video_id for item in feed.items] == [vid(LOVED, 25), vid(LOVED, 24)]


def test_candidate_window(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add_videos(session, PLAIN, range(30, 31), seen=NOW - timedelta(days=30))

    feed = build(sessions)

    assert vid(PLAIN, 30) not in {item.video_id for item in feed.items}


def test_empty_pool_stores_an_empty_feed(tmp_path: Path) -> None:
    factory = open_database(tmp_path / "empty.sqlite")
    feed = build(factory)

    assert feed.items == []
    with factory() as session:
        assert feeds.list_feeds(session)[0].item_count == 0
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def test_latest_feed_per_date_and_history(sessions: sessionmaker[Session]) -> None:
    yesterday = build(sessions, feed_date=TODAY - timedelta(days=1))
    build(sessions, feed_date=TODAY)
    refreshed = build(sessions, feed_date=TODAY, settings=Settings(feed_size=2))

    with sessions() as session:
        assert feeds.get_feed(session, TODAY) == refreshed
        assert feeds.get_feed(session, TODAY - timedelta(days=2)) is None
        history = feeds.list_feeds(session)
    assert [(s.id, s.date, s.item_count) for s in history] == [
        (refreshed.id, TODAY, 2),
        (yesterday.id, TODAY - timedelta(days=1), 6),
    ]


def test_refresh_feed_polls_then_builds(sessions: sessionmaker[Session]) -> None:
    calls: list[str] = []

    def poll() -> None:
        calls.append("poll")
        with sessions.begin() as session:
            add_videos(session, LOVED, range(40, 41))

    feed = feeds.refresh_feed(
        sessions=sessions, poll=poll, settings=SETTINGS, rng=random.Random(0), now=NOW
    )

    assert calls == ["poll"]
    assert feed.date == feeds.local_today(NOW)
    assert vid(LOVED, 40) in {item.video_id for item in feed.items}


def test_refresh_feed_survives_a_failing_poll(sessions: sessionmaker[Session]) -> None:
    def poll() -> None:
        raise RuntimeError("YouTube is down")

    feed = feeds.refresh_feed(sessions=sessions, poll=poll, settings=SETTINGS, now=NOW)

    assert len(feed.items) == 6
