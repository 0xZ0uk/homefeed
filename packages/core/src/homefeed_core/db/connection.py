import sqlite3
import time
from pathlib import Path

import sqlite_vec
from sqlalchemy import Engine
from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.orm import Session, sessionmaker

# How long a connection waits for another process's write lock before failing.
BUSY_TIMEOUT_SECONDS = 30.0


def connect(path: Path, *, check_same_thread: bool = True) -> sqlite3.Connection:
    """Open a raw connection with WAL, foreign keys and sqlite-vec configured.

    The connection is returned in autocommit mode so callers control transactions
    explicitly (`BEGIN` / `COMMIT`); the session factory switches it to `autocommit=False`.
    """
    conn = sqlite3.connect(
        path,
        timeout=BUSY_TIMEOUT_SECONDS,
        autocommit=True,
        check_same_thread=check_same_thread,
    )
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        _enable_wal(conn)
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        conn.close()
        raise
    return conn


def _enable_wal(conn: sqlite3.Connection) -> None:
    """Switch to WAL (persistent once set on the file).

    Switching a brand-new file can fail with "database is locked" without consulting the
    busy timeout when another process is opening it at the same moment, so retry.
    """
    deadline = time.monotonic() + BUSY_TIMEOUT_SECONDS
    while True:
        try:
            mode = conn.execute("PRAGMA journal_mode = WAL").fetchone()[0]
        except sqlite3.OperationalError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.01)
            continue
        if mode != "wal":
            raise sqlite3.OperationalError(f"Could not enable WAL (journal mode is {mode!r})")
        return


def create_engine(path: Path) -> Engine:
    """Create a SQLAlchemy engine whose pooled connections come from `connect`."""

    def creator() -> sqlite3.Connection:
        # Pooled connections move between threads (FastAPI runs sync handlers in a pool).
        conn = connect(path, check_same_thread=False)
        # PEP 249 transactions, so DDL and SELECTs are transactional too.
        conn.autocommit = False
        return conn

    return sa_create_engine(f"sqlite:///{path}", creator=creator)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
