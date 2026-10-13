from datetime import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import find_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# LLM providers for video tagging (see homefeed_core.llm_tags). "openrouter" is the
# hosted OpenRouter API (openrouter.ai), "ollama" a local Ollama server and "none"
# turns tagging off.
type LLMProviderName = Literal["openrouter", "ollama", "none"]
# Embedding providers (see homefeed_core.embeddings): "local" runs a fastembed
# model in the process, "openrouter" calls OpenRouter's embeddings API.
type EmbeddingProviderName = Literal["local", "openrouter"]

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables and `.env`.

    The settings in `user_settings.UserSettings` (feed size, schedule, LLM tagging, ...)
    can also be changed on the settings screen, which stores them in the database; the
    values here are then only their defaults. Read those through
    `user_settings.get_user_settings`, not from here.
    """

    model_config = SettingsConfigDict(extra="ignore")

    data_dir: Path = Path("data")
    database_path: Path = Path("data/homefeed.sqlite")
    feed_size: int = 20
    # Feed slots reserved for exploring under-rated channels (Thompson sampling).
    feed_exploration_slots: int = 3
    # Local time (the user's time zone, by default the process's TZ) when the worker
    # builds the day's feed.
    feed_refresh_time: time = time(6, 0)
    # Run the worker's scheduled jobs inside the API process instead of a separate
    # worker process (one process, e.g. the desktop app). Docker Compose keeps a worker.
    run_worker_in_api: bool = False
    # Local time when the worker trains the ranking model (before the day's feed).
    model_training_time: time = time(3, 0)
    # Local time when the worker runs the live Gateway smoke test against real YouTube
    # (see homefeed_core.smoke_test); unset means it never runs. Opt-in: it uses the
    # network, and its outcome shows on the status page.
    gateway_smoke_test_time: time | None = None
    # Hard duration bounds for feed videos, in seconds; unset means no bound.
    feed_min_duration_seconds: int | None = None
    feed_max_duration_seconds: int | None = None
    # How far back (by when a video entered the candidate pool) the feed looks.
    feed_candidate_days: int = 7
    # Content embeddings (see homefeed_core.embeddings): "local" downloads a
    # fastembed (ONNX) model into DATA_DIR/models and runs it in the process (it must
    # make 384-dimensional vectors); "openrouter" calls OpenRouter's embeddings API with
    # OPENROUTER_API_KEY, asking for 384 dimensions (e.g. perplexity/pplx-embed-v1-0.6b).
    # Changing the model re-embeds every stored video on the worker's next enrichment run,
    # and the ranking model is set aside until it is retrained on the new vectors.
    embedding_provider: EmbeddingProviderName = "local"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_timeout_seconds: float = 60.0
    # Similarity calibration; unset uses the values measured for the embedding model (see
    # embeddings.CALIBRATIONS). similarity_floor: below it a candidate counts as unrelated
    # to a rated video; topic_similarity_floor: likewise for a topic's description;
    # tag_merge_threshold: from it a proposed tag merges into the most similar existing
    # one (higher merges less; see homefeed_core.tags).
    similarity_floor: float | None = Field(default=None, ge=-1, lt=1)
    topic_similarity_floor: float | None = Field(default=None, ge=-1, lt=1)
    tag_merge_threshold: float | None = Field(default=None, ge=-1, le=1)
    # LLM tagging (topic, depth, clickbait, rage-bait, specific tags); see
    # homefeed_core.llm_tags. The default is the hosted OpenRouter API, which needs
    # OPENROUTER_API_KEY: without one, tagging is skipped (with a warning) and ranking
    # goes on without tags.
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
    # At most this many videos are tagged per enrichment run, to bound cost (also how
    # fast a prompt version bump retags the library).
    llm_max_tags_per_run: int = 200
    # Tag discovery (see homefeed_core.tag_discovery): at most this many new candidates per
    # subscribed tag per day come from searching YouTube for it (0 turns discovery off).
    tag_discovery_per_day: int = Field(default=10, ge=0)
    # SponsorBlock (see homefeed_core.sponsorblock): the server, and the comma-separated
    # categories the watch page skips (empty turns skipping off).
    sponsorblock_url: str = "https://sponsor.ajay.app"
    sponsorblock_categories: str = "sponsor,selfpromo,interaction"


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
