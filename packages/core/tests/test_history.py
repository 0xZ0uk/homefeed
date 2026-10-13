from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import open_database
from homefeed_core.gateway import Video
from homefeed_core.history import get_history_entry, resume_position, search_history
from homefeed_core.ratings import set_rating
from homefeed_core.videos import store_video
from homefeed_core.watch_events import WatchEventType, record_watch_event


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def store(
    sessions: sessionmaker[Session],
    video_id: str,
    title: str,
    channel_title: str = "Some Channel",
    duration: int | None = 600,
) -> None:
    with sessions.begin() as session:
        store_video(
            session,
            Video(
                id=video_id,
                title=title,
                channel_id=f"UC{video_id:_<22}",
                channel_title=channel_title,
                duration_seconds=duration,
            ),
        )


def record(
    sessions: sessionmaker[Session],
    video_id: str,
    *events: tuple[WatchEventType, float],
    minute: int = 0,
    duration: float | None = 600.0,
) -> None:
    with sessions.begin() as session:
        for second, (event_type, position) in enumerate(events):
            record_watch_event(
                session,
                video_id,
                event_type,
                position,
                duration,
                at=f"2026-10-12T10:{minute:02d}:{second:02d}.000Z",
            )


@pytest.mark.parametrize(
    ("event_type", "position", "duration", "expected"),
    [
        ("pause", 120.0, 600.0, 120.0),
        ("close", 300.5, None, 300.5),
        ("seeked", 42.0, 600.0, 42.0),
        ("play", 0.0, 600.0, None),  # started over
        ("close", 4.9, 600.0, None),  # barely started
        ("close", 595.0, 600.0, None),  # practically finished
        ("ended", 600.0, 600.0, None),
        ("ended", 200.0, None, None),
    ],
)
def test_resume_position(
    event_type: str, position: float, duration: float | None, expected: float | None
) -> None:
    assert resume_position(event_type, position, duration) == expected


def test_history_lists_played_videos_newest_first(sessions: sessionmaker[Session]) -> None:
    store(sessions, "aaaaaaaaaaa", "Hand plane restoration", "Wood Shop")
    store(sessions, "bbbbbbbbbbb", "Sourdough basics", "Bread Lab")
    record(sessions, "aaaaaaaaaaa", ("play", 0), ("pause", 120), minute=1)
    record(sessions, "bbbbbbbbbbb", ("play", 0), ("ended", 600), minute=2)
    record(sessions, "ccccccccccc", ("close", 0), minute=3)  # opened, never played
    with sessions.begin() as session:
        set_rating(session, "bbbbbbbbbbb", 7.8)

    with sessions() as session:
        entries = search_history(session)

    assert [e.video_id for e in entries] == ["bbbbbbbbbbb", "aaaaaaaaaaa"]
    bread, wood = entries
    assert bread.title == "Sourdough basics"
    assert bread.channel_title == "Bread Lab"
    assert bread.finished
    assert bread.resume_position is None
    assert bread.score == 7.8
    assert wood.finished is False
    assert wood.position == 120
    assert wood.resume_position == 120
    assert wood.duration == 600
    assert wood.score is None
    assert wood.first_watched_at == "2026-10-12T10:01:00.000Z"
    assert wood.last_watched_at == "2026-10-12T10:01:01.000Z"


def test_rewatching_moves_a_video_to_the_top(sessions: sessionmaker[Session]) -> None:
    record(sessions, "aaaaaaaaaaa", ("play", 0), ("ended", 600), minute=1)
    record(sessions, "bbbbbbbbbbb", ("play", 0), minute=2)
    record(sessions, "aaaaaaaaaaa", ("play", 0), ("close", 250), minute=3)

    with sessions() as session:
        entries = search_history(session)

    assert [e.video_id for e in entries] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert entries[0].finished  # finished once before
    assert entries[0].resume_position == 250  # but left mid-way this time
    assert entries[0].first_watched_at == "2026-10-12T10:01:00.000Z"


def test_search_matches_every_word_in_title_or_channel(
    sessions: sessionmaker[Session],
) -> None:
    store(sessions, "aaaaaaaaaaa", "Hand plane restoration", "Wood Shop")
    store(sessions, "bbbbbbbbbbb", "Sourdough basics", "Bread Lab")
    store(sessions, "ccccccccccc", "Crème brûlée", "Pâtisserie")
    for minute, video_id in enumerate(["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]):
        record(sessions, video_id, ("play", 0), minute=minute)
    record(sessions, "ddddddddddd", ("play", 0), minute=9)  # no stored details

    with sessions() as session:

        def found(query: str) -> list[str]:
            return [e.video_id for e in search_history(session, query)]

        assert found("PLANE") == ["aaaaaaaaaaa"]
        assert found("wood restoration") == ["aaaaaaaaaaa"]  # title and channel
        assert found("wood bread") == []  # every word must match
        assert found("bread") == ["bbbbbbbbbbb"]
        assert found("CRÈME") == ["ccccccccccc"]  # not just ASCII
        assert found("pâtisserie") == ["ccccccccccc"]
        assert found("100%") == []  # no LIKE wildcards
        assert found("   ") == ["ddddddddddd", "ccccccccccc", "bbbbbbbbbbb", "aaaaaaaaaaa"]


def test_search_pages(sessions: sessionmaker[Session]) -> None:
    ids = [f"video{n:06d}" for n in range(5)]
    for minute, video_id in enumerate(ids):
        record(sessions, video_id, ("play", 0), minute=minute)

    with sessions() as session:
        first = search_history(session, limit=2)
        second = search_history(session, limit=2, offset=2)
        last = search_history(session, limit=2, offset=4)

    assert [e.video_id for e in first + second + last] == ids[::-1]


def test_entry_for_one_video(sessions: sessionmaker[Session]) -> None:
    store(sessions, "aaaaaaaaaaa", "Hand plane restoration", duration=None)
    record(sessions, "aaaaaaaaaaa", ("play", 0), ("seeked", 300), ("close", 310.5), minute=1)
    record(sessions, "bbbbbbbbbbb", ("play", 0), ("pause", 50), minute=2)
    record(sessions, "ccccccccccc", ("close", 30), minute=3)

    with sessions() as session:
        entry = get_history_entry(session, "aaaaaaaaaaa")
        assert get_history_entry(session, "ccccccccccc") is None  # never played
        assert get_history_entry(session, "zzzzzzzzzzz") is None

    assert entry is not None
    assert entry.resume_position == 310.5
    assert entry.duration == 600  # the player's, as nothing better is stored


def test_resume_uses_the_players_duration_when_none_is_stored(
    sessions: sessionmaker[Session],
) -> None:
    record(sessions, "aaaaaaaaaaa", ("play", 0), ("close", 95), duration=100.0)

    with sessions() as session:
        entry = get_history_entry(session, "aaaaaaaaaaa")

    assert entry is not None
    assert entry.resume_position is None


def test_leaving_before_playback_keeps_the_resume_position(
    sessions: sessionmaker[Session],
) -> None:
    record(sessions, "aaaaaaaaaaa", ("play", 0), ("close", 200), minute=1)
    record(sessions, "aaaaaaaaaaa", ("close", 0), minute=2)  # left before it loaded

    with sessions() as session:
        entry = get_history_entry(session, "aaaaaaaaaaa")

    assert entry is not None
    assert entry.resume_position == 200
    assert entry.last_watched_at == "2026-10-12T10:02:00.000Z"

    # Starting over and leaving early does start over next time.
    record(sessions, "aaaaaaaaaaa", ("play", 0), ("close", 3), minute=3)
    with sessions() as session:
        entry = get_history_entry(session, "aaaaaaaaaaa")
    assert entry is not None
    assert entry.resume_position is None
