from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import open_database
from homefeed_core.feeds import watched_video_ids
from homefeed_core.ratings import set_rating
from homefeed_core.watch_events import (
    WatchEvent,
    WatchEventType,
    abandoned_early,
    abandoned_early_video_ids,
    is_abandoned_early,
    list_watch_events,
    played_video_ids,
    record_watch_event,
)


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def record(
    sessions: sessionmaker[Session], video_id: str, *events: tuple[WatchEventType, float]
) -> None:
    with sessions.begin() as session:
        for second, (event_type, position) in enumerate(events):
            record_watch_event(
                session, video_id, event_type, position, 600.0, at=f"2026-10-12T10:00:{second:02d}Z"
            )


def test_record_stores_event_with_timestamp(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        event = record_watch_event(session, "v", "pause", 12.5, 300.0)

    assert event.video_id == "v"
    assert event.event_type == "pause"
    assert event.position == 12.5
    assert event.duration == 300.0
    assert event.at.endswith("Z")
    with sessions() as session:
        assert list_watch_events(session, "v") == [event]


def test_duration_may_be_unknown(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        event = record_watch_event(session, "v", "close", 0.0)
    assert event.duration is None


def test_events_are_listed_oldest_first(sessions: sessionmaker[Session]) -> None:
    record(sessions, "v", ("play", 0), ("pause", 5), ("play", 5), ("ended", 600))
    record(sessions, "other", ("play", 0))

    with sessions() as session:
        events = list_watch_events(session, "v")

    assert [(e.event_type, e.position) for e in events] == [
        ("play", 0),
        ("pause", 5),
        ("play", 5),
        ("ended", 600),
    ]


def test_unknown_type_is_rejected(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(ValueError), sessions.begin() as session:
        record_watch_event(session, "v", "timeupdate", 1.0)  # type: ignore[arg-type]
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.execute(
            text("INSERT INTO watch_events (video_id, event_type, position) VALUES ('v', 'x', 0)")
        )


def test_negative_position_is_rejected(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(IntegrityError), sessions.begin() as session:
        record_watch_event(session, "v", "pause", -1.0)


def test_played_and_watched_videos(sessions: sessionmaker[Session]) -> None:
    record(sessions, "played", ("play", 0), ("close", 3))
    record(sessions, "opened", ("close", 0))  # page opened, never played
    with sessions.begin() as session:
        set_rating(session, "rated", 6.3)

    with sessions() as session:
        assert played_video_ids(session) == {"played"}
        assert watched_video_ids(session) == {"played", "rated"}


@pytest.mark.parametrize(
    ("events", "abandoned"),
    [
        ([("play", 0), ("close", 20)], True),
        ([("play", 0), ("pause", 59.9)], True),
        ([("play", 0), ("pause", 30), ("play", 30), ("close", 45)], True),
        ([("play", 0), ("close", 60)], False),
        ([("play", 0), ("pause", 300), ("close", 300)], False),
        ([("play", 0), ("seeked", 120), ("close", 125)], False),
        ([("play", 0), ("seeked", 40), ("ended", 50)], False),
        ([("close", 0)], False),  # never played
        ([], False),
    ],
)
def test_abandoned_early(
    sessions: sessionmaker[Session],
    events: list[tuple[WatchEventType, float]],
    abandoned: bool,
) -> None:
    record(sessions, "v", *events)

    with sessions() as session:
        assert abandoned_early(session, "v") is abandoned
        assert ("v" in abandoned_early_video_ids(session)) is abandoned


def test_abandonment_spans_visits(sessions: sessionmaker[Session]) -> None:
    record(sessions, "v", ("play", 0), ("close", 10))
    with sessions() as session:
        assert abandoned_early(session, "v")

    record(sessions, "v", ("play", 10), ("close", 400))
    with sessions() as session:
        assert not abandoned_early(session, "v")
        assert abandoned_early_video_ids(session) == set()


def test_abandonment_threshold_is_configurable() -> None:
    events = [
        WatchEvent(1, "v", "play", 0.0, 600.0, "a"),
        WatchEvent(2, "v", "close", 90.0, 600.0, "b"),
    ]
    assert not is_abandoned_early(events)
    assert is_abandoned_early(events, threshold=120)
