from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory


@pytest.fixture
def database_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    path = tmp_path / "data" / "homefeed.sqlite"
    monkeypatch.setenv("DATABASE_PATH", str(path))
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    yield path
    factory = get_session_factory()
    factory.kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def test_startup_creates_and_migrates_database(database_path: Path) -> None:
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    assert database_path.exists()
    with get_session_factory()() as session:
        tables = session.execute(text("SELECT name FROM sqlite_master")).scalars().all()
    assert {"channels", "videos", "settings"} <= set(tables)
