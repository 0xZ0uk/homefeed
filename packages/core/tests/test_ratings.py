import math
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import open_database
from homefeed_core.db.connection import connect
from homefeed_core.db.migrate import load_migrations, migrate
from homefeed_core.ratings import delete_rating, get_rating, set_rating
from homefeed_core.scores import is_bottom_tier, is_good, is_top_tier, score_value


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def test_set_rating_creates_with_value(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        rating = set_rating(session, "dQw4w9WgXcQ", 6.6)

    assert rating.video_id == "dQw4w9WgXcQ"
    assert rating.score == 6.6
    assert math.isclose(rating.value, score_value(6.6))
    assert rating.rated_at == rating.updated_at
    assert rating.rated_at.endswith("Z")
    with sessions() as session:
        assert get_rating(session, "dQw4w9WgXcQ") == rating


def test_set_rating_updates_and_keeps_rated_at(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        first = set_rating(session, "v", 4.7)
    time.sleep(0.01)  # timestamps have millisecond resolution
    with sessions.begin() as session:
        second = set_rating(session, "v", 10.0)

    assert second.score == 10.0
    assert second.value == 1.0
    assert second.rated_at == first.rated_at
    assert second.updated_at > first.updated_at
    with sessions() as session:
        assert session.execute(text("SELECT count(*) FROM ratings")).scalar_one() == 1


def test_rating_does_not_require_a_stored_video(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_rating(session, "not-in-videos", 1.0)
    with sessions() as session:
        rating = get_rating(session, "not-in-videos")
    assert rating is not None and rating.value == -1.0


def test_delete_rating(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_rating(session, "v", 7.8)
    with sessions.begin() as session:
        assert delete_rating(session, "v") is True
        assert delete_rating(session, "v") is False
    with sessions() as session:
        assert get_rating(session, "v") is None


@pytest.mark.parametrize("score", [0.5, 10.5, 4.25])
def test_set_rating_rejects_invalid_scores(sessions: sessionmaker[Session], score: float) -> None:
    with pytest.raises(ValueError), sessions.begin() as session:
        set_rating(session, "v", score)
    with sessions() as session:
        assert get_rating(session, "v") is None


@pytest.mark.parametrize("score", [0.0, 11.0])
def test_table_rejects_out_of_range_scores(sessions: sessionmaker[Session], score: float) -> None:
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.execute(
            text("INSERT INTO ratings (video_id, score, value) VALUES ('v', :score, 0)"),
            {"score": score},
        )


def test_migration_converts_grades_to_scores(tmp_path: Path) -> None:
    """Migration 0018 maps each tier-list grade onto the 1 to 10 line by its value."""
    path = tmp_path / "homefeed.sqlite"
    migrations = load_migrations()
    [scores_migration] = [m for m in migrations if m.name == "rating_scores"]
    migrate(path, [m for m in migrations if m.version < scores_migration.version])
    grades = {"F--": 0, "D++": 9, "C--": 10, "C": 12, "C++": 14, "B--": 15, "A--": 20, "S++": 29}
    conn = connect(path)
    try:
        conn.executemany(
            "INSERT INTO ratings (video_id, grade, value, rated_at) VALUES (?, ?, ?, ?)",
            [(g, g, -1 + 2 * i / 29, "2026-01-01T00:00:00.000Z") for g, i in grades.items()],
        )
    finally:
        conn.close()

    migrate(path, migrations)

    conn = connect(path)
    try:
        rows = conn.execute("SELECT video_id, score, value, rated_at FROM ratings").fetchall()
    finally:
        conn.close()
    converted = {video_id: score for video_id, score, _, _ in rows}
    assert converted == {
        "F--": 1.0,
        "D++": 3.8,
        "C--": 4.1,
        "C": 4.7,
        "C++": 5.3,
        "B--": 5.7,
        "A--": 7.2,
        "S++": 10.0,
    }
    for _, score, value, rated_at in rows:
        assert math.isclose(value, score_value(score))
        assert rated_at == "2026-01-01T00:00:00.000Z"
    # Good, top and bottom tier keep their old boundaries (B--, A--, D++).
    assert not is_good(converted["C++"]) and is_good(converted["B--"])
    assert is_top_tier(converted["A--"])
    assert is_bottom_tier(converted["D++"]) and not is_bottom_tier(converted["C--"])
