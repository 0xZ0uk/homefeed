import sqlite3
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import (
    Migration,
    MigrationError,
    connect,
    load_migrations,
    migrate,
    open_database,
)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "data" / "homefeed.sqlite"


def dispose(factory: sessionmaker[Session]) -> None:
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


@pytest.fixture
def sessions(db_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(db_path)
    yield factory
    dispose(factory)


def table_names(path: Path) -> set[str]:
    conn = connect(path)
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    finally:
        conn.close()
    return {row[0] for row in rows}


def bundled_versions() -> list[int]:
    return [m.version for m in load_migrations()]


def recorded_versions(path: Path) -> list[int]:
    conn = connect(path)
    try:
        rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


def test_open_database_creates_file_and_initial_tables(
    db_path: Path, sessions: sessionmaker[Session]
) -> None:
    assert db_path.exists()
    assert {"channels", "videos", "settings", "schema_migrations"} <= table_names(db_path)
    assert recorded_versions(db_path) == bundled_versions()


def test_migrate_is_idempotent(db_path: Path, sessions: sessionmaker[Session]) -> None:
    assert migrate(db_path) == []
    dispose(open_database(db_path))
    assert recorded_versions(db_path) == bundled_versions()


def test_session_uses_wal_foreign_keys_and_sqlite_vec(sessions: sessionmaker[Session]) -> None:
    with sessions() as session:
        assert session.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
        assert session.execute(text("PRAGMA foreign_keys")).scalar_one() == 1
        assert session.execute(text("SELECT vec_version()")).scalar_one().startswith("v")


def test_sqlite_vec_virtual_table_works(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        session.execute(text("CREATE VIRTUAL TABLE vectors USING vec0(embedding float[2])"))
        session.execute(
            text("INSERT INTO vectors (rowid, embedding) VALUES (1, '[1, 0]'), (2, '[0, 1]')")
        )
    with sessions() as session:
        nearest = session.execute(
            text(
                "SELECT rowid FROM vectors WHERE embedding MATCH '[0.9, 0.1]' "
                "ORDER BY distance LIMIT 1"
            )
        ).scalar_one()
    assert nearest == 1


def test_writes_are_visible_to_another_process_style_factory(
    db_path: Path, sessions: sessionmaker[Session]
) -> None:
    with sessions.begin() as session:
        session.execute(text("INSERT INTO channels (id, title) VALUES ('UC1', 'One')"))
        session.execute(
            text("INSERT INTO videos (id, channel_id, title) VALUES ('v1', 'UC1', 'Video')")
        )
        session.execute(text("INSERT INTO settings (key, value) VALUES ('feed_size', '15')"))

    other = open_database(db_path)
    with other() as session:
        row = session.execute(
            text(
                "SELECT videos.title, channels.title, videos.is_short, videos.created_at "
                "FROM videos JOIN channels ON channels.id = videos.channel_id"
            )
        ).one()
        setting = session.execute(text("SELECT value FROM settings")).scalar_one()
    dispose(other)
    assert row[:3] == ("Video", "One", 0)
    assert row[3].endswith("Z")
    assert setting == "15"


def test_rolled_back_session_writes_nothing(sessions: sessionmaker[Session]) -> None:
    with sessions() as session:
        session.execute(text("INSERT INTO channels (id, title) VALUES ('UC1', 'One')"))
        session.rollback()
    with sessions() as session:
        assert session.execute(text("SELECT count(*) FROM channels")).scalar_one() == 0


def test_video_requires_existing_channel(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.execute(
            text("INSERT INTO videos (id, channel_id, title) VALUES ('v1', 'nope', 'Video')")
        )


def test_settings_value_must_be_json(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.execute(text("INSERT INTO settings (key, value) VALUES ('k', 'not json')"))


def test_bundled_migrations_are_numbered_from_one() -> None:
    versions = sorted(m.version for m in load_migrations())
    assert versions == list(range(1, len(versions) + 1))


def test_migrations_apply_in_version_order(tmp_path: Path) -> None:
    (tmp_path / "0002_add_b.sql").write_text("CREATE TABLE b (a_id REFERENCES a (id));")
    (tmp_path / "0001_add_a.sql").write_text("CREATE TABLE a (id INTEGER PRIMARY KEY);")
    db_path = tmp_path / "db.sqlite"

    applied = migrate(db_path, load_migrations(tmp_path))

    assert [(m.version, m.name) for m in applied] == [(1, "add_a"), (2, "add_b")]
    assert {"a", "b"} <= table_names(db_path)


def test_later_migration_applies_on_top_of_existing_database(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    first = Migration(1, "add_a", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    migrate(db_path, [first])

    applied = migrate(db_path, [first, Migration(2, "add_b", "CREATE TABLE b (x);")])

    assert [m.version for m in applied] == [2]
    assert recorded_versions(db_path) == [1, 2]


def test_version_gaps_are_allowed(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    first = Migration(1, "add_a", "CREATE TABLE a (x);")
    third = Migration(3, "add_c", "CREATE TABLE c (x);")
    migrate(db_path, [first, third])

    # A lower-numbered migration merged later still applies.
    applied = migrate(db_path, [first, Migration(2, "add_b", "CREATE TABLE b (x);"), third])

    assert [m.version for m in applied] == [2]
    assert recorded_versions(db_path) == [1, 2, 3]


def test_failed_migration_is_rolled_back(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    good = Migration(1, "good", "CREATE TABLE a (id INTEGER PRIMARY KEY);")
    bad = Migration(2, "bad", "CREATE TABLE b (x); INSERT INTO missing VALUES (1);")

    with pytest.raises(MigrationError, match="0002_bad"):
        migrate(db_path, [good, bad])

    assert recorded_versions(db_path) == [1]
    assert "b" not in table_names(db_path)


def test_migration_leaving_foreign_key_violations_is_rolled_back(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    bad = Migration(
        1,
        "orphans",
        "CREATE TABLE a (id INTEGER PRIMARY KEY);"
        "CREATE TABLE b (a_id REFERENCES a (id));"
        "INSERT INTO b VALUES (42);",
    )

    with pytest.raises(MigrationError, match="foreign key"):
        migrate(db_path, [bad])

    assert recorded_versions(db_path) == []


def test_unknown_applied_version_is_rejected(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    migrate(db_path, [Migration(1, "a", "CREATE TABLE a (x);")])

    with pytest.raises(MigrationError, match=r"\[1\]"):
        migrate(db_path, [])


@pytest.mark.parametrize("filename", ["1_short.sql", "0001-dash.sql", "0001_Upper.sql"])
def test_bad_migration_filename_is_rejected(tmp_path: Path, filename: str) -> None:
    (tmp_path / filename).write_text("SELECT 1;")

    with pytest.raises(MigrationError, match="filename"):
        load_migrations(tmp_path)


def test_duplicate_migration_version_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "0001_a.sql").write_text("SELECT 1;")
    (tmp_path / "0001_b.sql").write_text("SELECT 1;")

    with pytest.raises(MigrationError, match="Duplicate"):
        load_migrations(tmp_path)


def test_concurrent_migrate_applies_each_migration_once(tmp_path: Path) -> None:
    db_path = tmp_path / "db.sqlite"
    migrations = [
        Migration(1, "a", "CREATE TABLE a (x);"),
        Migration(2, "b", "CREATE TABLE b (x);"),
    ]
    results: list[list[Migration]] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            results.append(migrate(db_path, migrations))
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(m.version for result in results for m in result) == [1, 2]
    assert recorded_versions(db_path) == [1, 2]


def test_connect_returns_configured_autocommit_connection(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True)
    conn = connect(db_path)
    try:
        assert conn.autocommit is True
        assert conn.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert conn.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert conn.execute("SELECT vec_version()").fetchone() is not None
    finally:
        conn.close()
    assert isinstance(conn, sqlite3.Connection)
