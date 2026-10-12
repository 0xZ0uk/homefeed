"""A small versioned migration runner.

Migrations are SQL files in `migrations/` named `NNNN_description.sql`, applied in
version order. Each runs in its own `BEGIN IMMEDIATE` transaction together with its
row in `schema_migrations`, so a failed migration leaves no trace and concurrent
runners (api and worker starting together) apply each migration exactly once.

To change the schema, add the next numbered file. Never edit an applied migration.
Migrations run with foreign keys off (so tables can be rebuilt) and are checked with
`PRAGMA foreign_key_check` before commit. Don't put `BEGIN`/`COMMIT` in the files.
"""

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from homefeed_core.db.connection import connect

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_FILENAME = re.compile(r"^(\d{4})_([a-z0-9_]+)\.sql$")


class MigrationError(Exception):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Read the migration files in `directory`, sorted by version."""
    migrations: dict[int, Migration] = {}
    for path in directory.glob("*.sql"):
        match = _FILENAME.match(path.name)
        if match is None:
            raise MigrationError(f"Bad migration filename {path.name!r}; expected NNNN_name.sql")
        version = int(match.group(1))
        if version in migrations:
            raise MigrationError(f"Duplicate migration version {version} ({path.name})")
        migrations[version] = Migration(version, match.group(2), path.read_text())
    return [migrations[v] for v in sorted(migrations)]


def migrate(path: Path, migrations: list[Migration] | None = None) -> list[Migration]:
    """Apply pending migrations to the database at `path`; return the ones applied."""
    if migrations is None:
        migrations = load_migrations()
    conn = connect(path)
    try:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            )
            """
        )
        _check_known(conn, migrations)
        return [m for m in migrations if _apply(conn, m)]
    finally:
        conn.close()


def applied_versions(conn: sqlite3.Connection) -> set[int]:
    return {row[0] for row in conn.execute("SELECT version FROM schema_migrations")}


def _check_known(conn: sqlite3.Connection, migrations: list[Migration]) -> None:
    unknown = applied_versions(conn) - {m.version for m in migrations}
    if unknown:
        raise MigrationError(
            f"Database has migrations this code doesn't know about: {sorted(unknown)}"
        )


def _apply(conn: sqlite3.Connection, migration: Migration) -> bool:
    """Apply one migration unless already applied. Returns whether it ran."""
    label = f"{migration.version:04d}_{migration.name}"
    conn.execute("BEGIN IMMEDIATE")
    try:
        if migration.version in applied_versions(conn):
            conn.execute("ROLLBACK")
            return False
        conn.executescript(migration.sql)
        if conn.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise MigrationError(f"Migration {label} leaves foreign key violations")
        conn.execute(
            "INSERT INTO schema_migrations (version, name) VALUES (?, ?)",
            (migration.version, migration.name),
        )
        conn.execute("COMMIT")
    except BaseException as error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        if isinstance(error, sqlite3.Error):
            raise MigrationError(f"Migration {label} failed: {error}") from error
        raise
    return True
