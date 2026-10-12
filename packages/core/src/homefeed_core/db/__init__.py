"""The shared SQLite database: connections, sessions and schema migrations.

API and worker both call `get_session_factory()` (or `open_database(path)` in tests),
which creates the file if needed and applies pending migrations before returning a
SQLAlchemy session factory. Every connection uses WAL, enforces foreign keys and has
sqlite-vec loaded.
"""

from functools import lru_cache
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.config import get_settings
from homefeed_core.db.connection import connect, create_engine, create_session_factory
from homefeed_core.db.migrate import Migration, MigrationError, load_migrations, migrate

__all__ = [
    "Migration",
    "MigrationError",
    "connect",
    "create_engine",
    "create_session_factory",
    "get_session_factory",
    "load_migrations",
    "migrate",
    "open_database",
]


def open_database(path: Path) -> sessionmaker[Session]:
    """Create the database at `path` if needed, migrate it, and return a session factory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    migrate(path)
    return create_session_factory(create_engine(path))


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """The process-wide session factory for the configured `DATABASE_PATH`."""
    return open_database(get_settings().database_path)
