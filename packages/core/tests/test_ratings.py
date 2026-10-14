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
        rating = set_rating(session, "dQw4w9WgXcQ", 7)

    assert rating.video_id == "dQw4w9WgXcQ"
    assert rating.score == 7
    assert math.isclose(rating.value, score_value(7))
    assert rating.rated_at == rating.updated_at
    assert rating.rated_at.endswith("Z")
    with sessions() as session:
        assert get_rating(session, "dQw4w9WgXcQ") == rating


def test_set_rating_updates_and_keeps_rated_at(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        first = set_rating(session, "v", 5)
    time.sleep(0.01)  # timestamps have millisecond resolution
    with sessions.begin() as session:
        second = set_rating(session, "v", 10)

    assert second.score == 10
    assert second.value == 1.0
    assert second.rated_at == first.rated_at
    assert second.updated_at > first.updated_at
    with sessions() as session:
        assert session.execute(text("SELECT count(*) FROM ratings")).scalar_one() == 1


def test_rating_does_not_require_a_stored_video(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_rating(session, "not-in-videos", 1)
    with sessions() as session:
        rating = get_rating(session, "not-in-videos")
    assert rating is not None and rating.value == -1.0


def test_delete_rating(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_rating(session, "v", 8)
    with sessions.begin() as session:
        assert delete_rating(session, "v") is True
        assert delete_rating(session, "v") is False
    with sessions() as session:
        assert get_rating(session, "v") is None


def test_set_rating_accepts_every_whole_score(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        for score in range(1, 11):
            rating = set_rating(session, f"v{score}", score)
            assert rating.score == score and isinstance(rating.score, int)
        types = session.execute(text("SELECT DISTINCT typeof(score) FROM ratings")).scalars().all()
    assert types == ["integer"]


def test_set_rating_takes_a_whole_float_as_that_score(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        rating = set_rating(session, "v", 7.0)  # type: ignore[arg-type]
    assert rating.score == 7 and isinstance(rating.score, int)
    assert math.isclose(rating.value, score_value(7))


@pytest.mark.parametrize("score", [0, 11, 0.5, 10.5, 7.5, 4.25, True])
def test_set_rating_rejects_invalid_scores(sessions: sessionmaker[Session], score: float) -> None:
    with pytest.raises(ValueError), sessions.begin() as session:
        set_rating(session, "v", score)  # type: ignore[arg-type]
    with sessions() as session:
        assert get_rating(session, "v") is None


@pytest.mark.parametrize("score", [0, 11, 0.5, 10.5])
def test_table_rejects_out_of_range_scores(sessions: sessionmaker[Session], score: float) -> None:
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.execute(
            text("INSERT INTO ratings (video_id, score, value) VALUES ('v', :score, 0)"),
            {"score": score},
        )


def test_migration_converts_grades_to_scores(tmp_path: Path) -> None:
    """Migration 0018 maps each tier-list grade onto the 1 to 10 line by its value (one
    decimal; 0026 later rounds these to whole scores)."""
    path = tmp_path / "homefeed.sqlite"
    migrations = [m for m in load_migrations() if m.name != "integer_scores"]
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

    migrate(path, [m for m in migrations if m.version <= scores_migration.version])

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
        assert math.isclose(value, (score - 5.5) / 4.5)
        assert rated_at == "2026-01-01T00:00:00.000Z"
    # Good, top and bottom tier keep their old boundaries (B--, A--, D++).
    assert not converted["C++"] >= 5.5 and converted["B--"] >= 5.5
    assert converted["A--"] >= 7.0
    assert converted["D++"] <= 4.0 and not converted["C--"] <= 4.0


def test_migration_rounds_scores_to_whole_scores(tmp_path: Path) -> None:
    """Migration 0026 rounds one-decimal scores to whole scores, halves up, and
    recomputes the value; the rating times stay."""
    path = tmp_path / "homefeed.sqlite"
    migrations = load_migrations()
    [integer_migration] = [m for m in migrations if m.name == "integer_scores"]
    migrate(path, [m for m in migrations if m.version < integer_migration.version])
    old_scores = {
        "a": 1.0,
        "b": 1.4,
        "c": 5.4,
        "d": 5.5,
        "e": 6.4,
        "f": 6.5,
        "g": 9.4,
        "h": 9.5,
        "i": 10.0,
        "j": 7.0,
    }
    conn = connect(path)
    try:
        conn.executemany(
            "INSERT INTO ratings (video_id, score, value, rated_at, updated_at)"
            " VALUES (?, ?, ?, '2026-01-01T00:00:00.000Z', '2026-02-02T00:00:00.000Z')",
            [(v, s, (s - 5.5) / 4.5) for v, s in old_scores.items()],
        )
    finally:
        conn.close()

    migrate(path, migrations)

    conn = connect(path)
    try:
        rows = conn.execute(
            "SELECT video_id, score, typeof(score), value, rated_at, updated_at FROM ratings"
        ).fetchall()
        index = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index' AND name = 'ratings_rated_at'"
        ).fetchall()
    finally:
        conn.close()
    assert {v: score for v, score, *_ in rows} == {
        "a": 1,
        "b": 1,
        "c": 5,
        "d": 6,
        "e": 6,
        "f": 7,
        "g": 9,
        "h": 10,
        "i": 10,
        "j": 7,
    }
    for _, score, type_, value, rated_at, updated_at in rows:
        assert type_ == "integer"
        assert math.isclose(value, score_value(score))
        assert (rated_at, updated_at) == ("2026-01-01T00:00:00.000Z", "2026-02-02T00:00:00.000Z")
    assert index == [("ratings_rated_at",)]
    # The same "good" verdict as before for every old score (>= 5.5 is now >= 6).
    verdicts = {v: is_good(score) for v, score, *_ in rows}
    assert verdicts == {v: s >= 5.5 for v, s in old_scores.items()}
    assert is_top_tier(7) and is_bottom_tier(4)
