import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import open_database
from homefeed_core.feedback import (
    LESS,
    MORE,
    clear_feedback,
    get_feedback,
    list_feedback,
    set_feedback,
)
from homefeed_core.ratings import list_ratings

CHANNEL = "UC" + "f" * 22
A, B, C = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    with factory.begin() as session:
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, 'Channel')"), {"id": CHANNEL}
        )
        for video_id in (A, B, C):
            session.execute(
                text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :channel, 'Video')"),
                {"id": video_id, "channel": CHANNEL},
            )
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def test_migration_creates_the_table(sessions: sessionmaker[Session]) -> None:
    with sessions() as session:
        columns = session.execute(text("SELECT name FROM pragma_table_info('video_feedback')"))
        assert [row[0] for row in columns] == ["video_id", "signal", "created_at", "updated_at"]


def test_set_feedback_creates_it(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        given = set_feedback(session, A, MORE)

    assert given is not None
    assert (given.video_id, given.signal) == (A, 1)
    assert given.created_at == given.updated_at
    assert given.created_at.endswith("Z")
    with sessions() as session:
        assert get_feedback(session, A) == given
        assert get_feedback(session, B) is None


def test_set_feedback_replaces_the_signal_and_keeps_when_it_was_first_given(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        first = set_feedback(session, A, MORE)
    time.sleep(0.01)  # timestamps have millisecond resolution
    with sessions.begin() as session:
        second = set_feedback(session, A, LESS)

    assert first is not None and second is not None
    assert second.signal == -1
    assert second.created_at == first.created_at
    assert second.updated_at > first.updated_at
    with sessions() as session:
        assert session.execute(text("SELECT count(*) FROM video_feedback")).scalar_one() == 1


def test_repeating_a_signal_changes_nothing(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        first = set_feedback(session, A, MORE)
    time.sleep(0.01)
    with sessions.begin() as session:
        again = set_feedback(session, A, MORE)

    assert again == first


def test_a_video_that_is_not_stored_gets_no_feedback(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        assert set_feedback(session, "zzzzzzzzzzz", MORE) is None
    with sessions() as session:
        assert list_feedback(session) == []


@pytest.mark.parametrize("signal", [0, 2, -2, True, 1.5, "1", None])
def test_only_more_and_less_are_signals(sessions: sessionmaker[Session], signal: object) -> None:
    with sessions.begin() as session, pytest.raises(ValueError, match="neither 1"):
        set_feedback(session, A, signal)  # type: ignore[arg-type]
    with sessions() as session:
        assert list_feedback(session) == []


def test_the_database_only_stores_more_and_less(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        session.execute(
            text("INSERT INTO video_feedback (video_id, signal) VALUES (:id, 1)"), {"id": A}
        )
    with sessions() as session, pytest.raises(IntegrityError):
        session.execute(
            text("INSERT INTO video_feedback (video_id, signal) VALUES (:id, 0)"), {"id": B}
        )


def test_clear_feedback(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_feedback(session, A, LESS)
        set_feedback(session, B, MORE)
    with sessions.begin() as session:
        assert clear_feedback(session, A) is True
        assert clear_feedback(session, A) is False
        assert clear_feedback(session, "zzzzzzzzzzz") is False
    with sessions() as session:
        assert get_feedback(session, A) is None
        assert [item.video_id for item in list_feedback(session)] == [B]


def test_list_feedback_is_oldest_first(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_feedback(session, C, MORE)
    time.sleep(0.01)
    with sessions.begin() as session:
        set_feedback(session, A, LESS)
        set_feedback(session, B, MORE)  # the same moment as A: ordered by video

    with sessions() as session:
        assert [(item.video_id, item.signal) for item in list_feedback(session)] == [
            (C, 1),
            (A, -1),
            (B, 1),
        ]


def test_feedback_goes_with_its_video(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_feedback(session, A, MORE)
        session.execute(text("DELETE FROM videos WHERE id = :id"), {"id": A})
        assert get_feedback(session, A) is None


def test_feedback_is_not_a_rating(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_feedback(session, A, MORE)
        set_feedback(session, B, LESS)
        assert list_ratings(session) == []
