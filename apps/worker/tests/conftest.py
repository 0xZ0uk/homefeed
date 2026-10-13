from collections.abc import Iterator
from pathlib import Path

import pytest

from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory


@pytest.fixture(autouse=True)
def database(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A throwaway database, for the user settings `register_jobs` reads."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    yield
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()
