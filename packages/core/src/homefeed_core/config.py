from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import find_dotenv
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# LLM providers for video tagging (see homefeed_core.llm_tags). "openrouter" is the
# hosted OpenRouter API (openrouter.ai), "ollama" a local Ollama server and "none"
# turns tagging off.
type LLMProviderName = Literal["openrouter", "ollama", "none"]


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables and `.env`."""

    model_config = SettingsConfigDict(extra="ignore")

    data_dir: Path = Path("data")
    database_path: Path = Path("data/homefeed.sqlite")
    feed_size: int = 15
    # Feed slots reserved for exploring under-rated channels (Thompson sampling).
    feed_exploration_slots: int = 3
    # Local time (the process's TZ) when the worker builds the day's feed.
    feed_refresh_time: time = time(6, 0)
    # Local time when the worker trains the ranking model (before the day's feed).
    model_training_time: time = time(3, 0)
    # Hard duration bounds for feed videos, in seconds; unset means no bound.
    feed_min_duration_seconds: int | None = None
    feed_max_duration_seconds: int | None = None
    # How far back (by when a video entered the candidate pool) the feed looks.
    feed_candidate_days: int = 7
    # sentence-transformers model for content embeddings (downloaded into DATA_DIR/models).
    # Changing it re-embeds every video on its next enrichment; it must be 384-dimensional.
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    # LLM tagging (topic, depth, clickbait, rage-bait); see homefeed_core.llm_tags. The
    # default is the hosted OpenRouter API, which needs OPENROUTER_API_KEY: without one,
    # tagging is skipped (with a warning) and ranking goes on without tags.
    llm_provider: LLMProviderName = "openrouter"
    # Model name for the provider; empty means the provider's default
    # (openrouter: google/gemini-2.5-flash-lite, ollama: llama3.1:8b).
    llm_model: str = ""
    # API base URL; empty means the provider's default
    # (openrouter: https://openrouter.ai/api/v1, ollama: http://localhost:11434).
    llm_base_url: str = ""
    # OpenRouter API key (https://openrouter.ai/settings/keys).
    openrouter_api_key: SecretStr | None = None
    llm_timeout_seconds: float = 60.0
    # At most this many videos are tagged per enrichment run, to bound cost.
    llm_max_tags_per_run: int = 200


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
