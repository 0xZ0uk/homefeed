from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.channel_health import PICKS_WINDOW_DAYS, ChannelHealth, channel_health
from homefeed_core.curation import subscribe, unsubscribe
from homefeed_core.db import open_database
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.gateway.fake import FakeGateway, make_channel
from homefeed_core.scores import score_value
from homefeed_core.watch_events import WatchEventType, record_watch_event

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
WOOD = make_channel("UC" + "w" * 22, title="Woodworking")
BIRDS = make_channel("UC" + "b" * 22, title="birds")
IDLE = make_channel("UC" + "i" * 22, title="Idle")
GONE = make_channel("UC" + "g" * 22, title="Gone")


def stamp(at: datetime) -> str:
    return format_timestamp(at)


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    gateway = FakeGateway()
    for channel in (WOOD, BIRDS, IDLE, GONE):
        gateway.add_channel(channel)
    with factory.begin() as session:
        for channel in (WOOD, BIRDS, IDLE, GONE):
            subscribe(session, gateway, channel.url or "")
        unsubscribe(session, GONE.id)  # known, with videos, but not subscribed
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def video(session: Session, channel_id: str, n: int) -> str:
    """A stored video of the channel; returns its id."""
    video_id = f"{channel_id[2]}{n:010d}"
    session.execute(
        text("INSERT OR IGNORE INTO videos (id, channel_id, title) VALUES (:id, :channel, 'v')"),
        {"id": video_id, "channel": channel_id},
    )
    return video_id


def feed(session: Session, at: datetime, video_ids: list[str], *, dismissed: bool = False) -> None:
    """A feed built at `at` holding the videos."""
    feed_id = session.execute(
        text("INSERT INTO feeds (date, created_at) VALUES (:date, :at) RETURNING id"),
        {"date": at.date().isoformat(), "at": stamp(at)},
    ).scalar_one()
    for position, video_id in enumerate(video_ids):
        session.execute(
            text(
                """
                INSERT INTO feed_items (feed_id, video_id, position, source, score, breakdown,
                                        explanation, dismissed_at)
                VALUES (:feed, :video, :position, 'subscription', 0.5, '{}', 'x', :dismissed)
                """
            ),
            {
                "feed": feed_id,
                "video": video_id,
                "position": position,
                "dismissed": stamp(at) if dismissed else None,
            },
        )


def rate(session: Session, video_id: str, score: int, at: datetime) -> None:
    session.execute(
        text(
            "INSERT INTO ratings (video_id, score, value, rated_at, updated_at) "
            "VALUES (:id, :score, :value, :at, :at)"
        ),
        {"id": video_id, "score": score, "value": score_value(score), "at": stamp(at)},
    )


def play(
    session: Session, video_id: str, at: datetime, event_type: WatchEventType = "play"
) -> None:
    record_watch_event(session, video_id, event_type, 5.0, 600.0, at=stamp(at))


def health(sessions: sessionmaker[Session], **kwargs: int) -> dict[str, ChannelHealth]:
    with sessions() as session:
        return {h.channel_id: h for h in channel_health(session, now=NOW, **kwargs)}


def test_the_window_is_thirty_days() -> None:
    assert PICKS_WINDOW_DAYS == 30


def test_every_subscribed_channel_is_listed_by_title_without_data_as_zeros(
    sessions: sessionmaker[Session],
) -> None:
    with sessions() as session:
        result = channel_health(session, now=NOW)

    assert [h.channel_id for h in result] == [BIRDS.id, IDLE.id, WOOD.id]
    assert result[0] == ChannelHealth(BIRDS.id, None, 0, None, 0, 0)


def test_picks_are_distinct_videos_in_feeds_of_the_window(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        a, b, c = (video(session, WOOD.id, n) for n in range(3))
        old = video(session, WOOD.id, 3)
        feed(session, NOW - timedelta(days=PICKS_WINDOW_DAYS + 1), [old])
        feed(session, NOW - timedelta(days=PICKS_WINDOW_DAYS - 1), [a, b])
        feed(session, NOW - timedelta(days=2), [a, c])  # a is picked again: still one pick
        feed(session, NOW - timedelta(hours=1), [a], dismissed=True)  # a refresh, a dismissal
        other = video(session, BIRDS.id, 0)
        feed(session, NOW - timedelta(days=1), [other])

    result = health(sessions)

    assert result[WOOD.id].picks == 3
    assert result[BIRDS.id].picks == 1
    assert result[IDLE.id].picks == 0
    assert health(sessions, days=1)[WOOD.id].picks == 1  # only the hour-old feed


def test_a_pick_counts_as_watched_once_played_or_rated(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        played, rated, both, untouched, opened = (video(session, WOOD.id, n) for n in range(5))
        feed(session, NOW - timedelta(days=3), [played, rated, both, untouched, opened])
        play(session, played, NOW - timedelta(days=2))
        play(session, played, NOW - timedelta(days=1))  # played twice: still one
        rate(session, rated, 6, NOW - timedelta(days=2))
        play(session, both, NOW - timedelta(days=2))
        rate(session, both, 8, NOW - timedelta(days=2))
        play(session, opened, NOW - timedelta(days=2), "close")  # opened, never played

    result = health(sessions)[WOOD.id]

    assert (result.picks, result.watched_picks) == (5, 3)


def test_last_watched_is_the_latest_play_or_rating_of_any_video_of_the_channel(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        old, recent, rated = (video(session, WOOD.id, n) for n in range(3))
        play(session, old, NOW - timedelta(days=40))
        play(session, recent, NOW - timedelta(days=9))
        play(session, recent, NOW - timedelta(days=8), "pause")  # not a watch
        rate(session, rated, 5, NOW - timedelta(days=20))
        elsewhere = video(session, BIRDS.id, 0)
        rate(session, elsewhere, 9, NOW - timedelta(days=10))
        late_rating = video(session, IDLE.id, 0)
        rate(session, late_rating, 4, NOW - timedelta(days=1))
        play(session, late_rating, NOW - timedelta(days=30))

    result = health(sessions)

    assert result[WOOD.id].last_watched_at == stamp(NOW - timedelta(days=9))
    assert result[BIRDS.id].last_watched_at == stamp(NOW - timedelta(days=10))
    assert result[IDLE.id].last_watched_at == stamp(NOW - timedelta(days=1))


def test_ratings_are_counted_and_averaged_whether_or_not_they_were_picks(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        for n, score in enumerate([7, 6, 6, 7]):
            rate(session, video(session, WOOD.id, n), score, NOW - timedelta(days=n + 50))
        rate(session, video(session, BIRDS.id, 0), 3, NOW)

    result = health(sessions)

    assert (result[WOOD.id].rating_count, result[WOOD.id].average_score) == (4, 6.5)
    assert (result[BIRDS.id].rating_count, result[BIRDS.id].average_score) == (1, 3.0)
    assert (result[IDLE.id].rating_count, result[IDLE.id].average_score) == (0, None)


def test_channels_that_are_not_subscribed_are_left_out(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        gone = video(session, GONE.id, 0)
        feed(session, NOW - timedelta(days=1), [gone])
        rate(session, gone, 9, NOW)

    assert GONE.id not in health(sessions)


def test_videos_that_are_not_stored_belong_to_no_channel(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        rate(session, "unknown_vid", 9, NOW)
        play(session, "unknown_vid", NOW)

    assert all(h.rating_count == 0 and h.last_watched_at is None for h in health(sessions).values())
