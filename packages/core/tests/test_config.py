from collections.abc import Iterator
from datetime import time
from pathlib import Path

import pytest

from homefeed_core.config import Settings, get_settings

ENV_VARS = (
    "DATA_DIR",
    "DATABASE_PATH",
    "FEED_SIZE",
    "FEED_REFRESH_TIME",
    "LLM_PROVIDER",
    "LLM_MODEL",
    "LLM_BASE_URL",
    "OPENROUTER_API_KEY",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.chdir(tmp_path)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults() -> None:
    settings = Settings()

    assert settings.feed_size == 15
    assert settings.feed_refresh_time == time(6, 0)
    # The hosted OpenRouter API, which stays off until OPENROUTER_API_KEY is set.
    assert settings.llm_provider == "openrouter"
    assert settings.openrouter_api_key is None


def test_loads_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_DIR", "/srv/homefeed")
    monkeypatch.setenv("DATABASE_PATH", "/srv/homefeed/db.sqlite")
    monkeypatch.setenv("FEED_SIZE", "10")
    monkeypatch.setenv("FEED_REFRESH_TIME", "07:30")
    monkeypatch.setenv("LLM_PROVIDER", "ollama")

    settings = Settings()

    assert settings.data_dir == Path("/srv/homefeed")
    assert settings.database_path == Path("/srv/homefeed/db.sqlite")
    assert settings.feed_size == 10
    assert settings.feed_refresh_time == time(7, 30)
    assert settings.llm_provider == "ollama"


def test_get_settings_reads_nearest_env_file_from_package_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text(
        "DATA_DIR=./data\nDATABASE_PATH=/abs/db.sqlite\nFEED_SIZE=20\nAPP_PASSWORD=web-only\n"
    )
    package_dir = tmp_path / "apps" / "worker"
    package_dir.mkdir(parents=True)
    monkeypatch.chdir(package_dir)

    settings = get_settings()

    assert settings.feed_size == 20
    assert settings.data_dir == tmp_path / "data"
    assert settings.database_path == Path("/abs/db.sqlite")
