import math
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import open_database
from homefeed_core.grades import grade_value
from homefeed_core.ratings import delete_rating, get_rating, set_rating


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def test_set_rating_creates_with_value(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        rating = set_rating(session, "dQw4w9WgXcQ", "B+")

    assert rating.video_id == "dQw4w9WgXcQ"
    assert rating.grade == "B+"
    assert math.isclose(rating.value, grade_value("B+"))
    assert rating.rated_at == rating.updated_at
    assert rating.rated_at.endswith("Z")
    with sessions() as session:
        assert get_rating(session, "dQw4w9WgXcQ") == rating


def test_set_rating_updates_and_keeps_rated_at(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        first = set_rating(session, "v", "C")
    time.sleep(0.01)  # timestamps have millisecond resolution
    with sessions.begin() as session:
        second = set_rating(session, "v", "S++")

    assert second.grade == "S++"
    assert second.value == 1.0
    assert second.rated_at == first.rated_at
    assert second.updated_at > first.updated_at
    with sessions() as session:
        assert session.execute(text("SELECT count(*) FROM ratings")).scalar_one() == 1


def test_rating_does_not_require_a_stored_video(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_rating(session, "not-in-videos", "F--")
    with sessions() as session:
        rating = get_rating(session, "not-in-videos")
    assert rating is not None and rating.value == -1.0


def test_delete_rating(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_rating(session, "v", "A")
    with sessions.begin() as session:
        assert delete_rating(session, "v") is True
        assert delete_rating(session, "v") is False
    with sessions() as session:
        assert get_rating(session, "v") is None


def test_table_rejects_invalid_grades(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.execute(text("INSERT INTO ratings (video_id, grade, value) VALUES ('v', 'Z', 0)"))
