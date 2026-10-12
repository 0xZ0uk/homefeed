from datetime import time
from functools import lru_cache
from pathlib import Path

from dotenv import find_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables and `.env`."""

    model_config = SettingsConfigDict(extra="ignore")

    data_dir: Path = Path("data")
    database_path: Path = Path("data/homefeed.sqlite")
    feed_size: int = 15
    # Local time (the process's TZ) when the worker builds the day's feed.
    feed_refresh_time: time = time(6, 0)
    # Hard duration bounds for feed videos, in seconds; unset means no bound.
    feed_min_duration_seconds: int | None = None
    feed_max_duration_seconds: int | None = None
    # How far back (by when a video entered the candidate pool) the feed looks.
    feed_candidate_days: int = 7
    llm_provider: str = "none"


@lru_cache
def get_settings() -> Settings:
    """Load settings, using the nearest `.env` at or above the working directory.

    Turbo runs each package's tasks from its own directory, so relative paths are
    resolved against the `.env` directory to keep api and worker on the same files.
    """
    env_file = find_dotenv(usecwd=True)
    # Pyright only sees the dataclass_transform fields, not BaseSettings' `_env_file` init arg.
    settings = Settings(_env_file=env_file or None)  # pyright: ignore[reportCallIssue]
    base = Path(env_file).parent if env_file else Path.cwd()
    return settings.model_copy(
        update={
            "data_dir": base / settings.data_dir,
            "database_path": base / settings.database_path,
        }
    )
