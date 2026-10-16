"""User settings: the configuration a user changes on the settings screen, stored in the
`settings` table (one JSON value per key) on top of the environment.

Precedence, per setting: a value stored in the database (source `user`) wins; otherwise
the environment variable or `.env` entry of the same name (`FEED_SIZE`, ...; source
`env`) applies, and otherwise the built-in default of `config.Settings` (source
`default`). Resetting a setting deletes its row, so it follows the environment again: an
install with everything in `.env` and nothing stored behaves as before. The time zone has
no variable of its own: its default is the system's (the process's `TZ`).

Everything else in `config.Settings` (paths, URLs, timeouts, the embedding model,
calibration, ...) stays environment-only.

    user = get_user_settings(session)            # effective values (a `UserSettings`)
    update_user_settings(session, {"feed_size": 30}, reset=["timezone"])

Values are validated on write (`update_user_settings` raises `ValueError`). A stored value
that no longer validates (edited by hand, or a constraint that changed) is logged and
ignored, so the setting falls back to its default.

The OpenRouter API key is stored in plain text, like the rest of the local database;
the API only ever returns whether one is set and its last characters (`key_hint`).
"""

import json
import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import time, tzinfo
from typing import Any, Literal, cast, get_args
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import tzlocal
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.browser_cookies import parse_browser_spec
from homefeed_core.config import LLMProviderName, Settings, get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.sponsorblock import CATEGORIES as SPONSORBLOCK_CATEGORIES

logger = logging.getLogger(__name__)

type SettingSource = Literal["default", "env", "user"]
# The `UserSettings` fields, for typing (a test checks they match).
type UserSettingKey = Literal[
    "feed_size",
    "feed_exploration_slots",
    "feed_max_topic_share",
    "feed_min_duration_seconds",
    "feed_max_duration_seconds",
    "feed_refresh_time",
    "model_training_time",
    "timezone",
    "llm_provider",
    "llm_model",
    "openrouter_api_key",
    "llm_max_tags_per_run",
    "tag_discovery_per_day",
    "sponsorblock_categories",
    "ytdlp_cookies_from_browser",
]

MAX_FEED_SIZE = 200
# The range of the share of a feed one followed topic may take (see homefeed_core.composer).
MIN_TOPIC_SHARE = 0.1
MAX_TOPIC_SHARE = 1.0
MAX_LLM_MODEL_LENGTH = 200
MAX_API_KEY_LENGTH = 500
# How many characters of the API key the settings screen shows.
KEY_HINT_LENGTH = 4


class UserSettings(BaseModel):
    """The effective user settings. Field names are the `settings` table keys and match
    `config.Settings`, whose (environment) values are the defaults."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    # Feed
    feed_size: int = Field(ge=1, le=MAX_FEED_SIZE)
    feed_exploration_slots: int = Field(ge=0, le=MAX_FEED_SIZE)
    feed_max_topic_share: float = Field(ge=MIN_TOPIC_SHARE, le=MAX_TOPIC_SHARE)
    feed_min_duration_seconds: int | None = Field(ge=0)
    feed_max_duration_seconds: int | None = Field(ge=0)
    # Schedule, in `timezone`
    feed_refresh_time: time
    model_training_time: time
    # IANA name, e.g. "Europe/Lisbon"; None is the system's time zone.
    timezone: str | None
    # LLM tagging (see homefeed_core.llm_tags) and tag discovery
    llm_provider: LLMProviderName
    llm_model: str = Field(max_length=MAX_LLM_MODEL_LENGTH)
    openrouter_api_key: SecretStr | None
    llm_max_tags_per_run: int = Field(ge=0, le=100_000)
    tag_discovery_per_day: int = Field(ge=0, le=1_000)
    # SponsorBlock categories the watch page skips (empty turns skipping off)
    sponsorblock_categories: tuple[str, ...]
    # The browser yt-dlp sends YouTube cookies from (see homefeed_core.browser_cookies);
    # None sends none.
    ytdlp_cookies_from_browser: str | None

    @field_validator("feed_refresh_time", "model_training_time")
    @classmethod
    def _whole_minutes(cls, value: time) -> time:
        if value.tzinfo is not None:
            raise ValueError("Give a local time without a UTC offset")
        return value.replace(second=0, microsecond=0)

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str | None) -> str | None:
        value = value.strip() if value else None
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"Unknown time zone: {value}") from error
        return value

    @field_validator("llm_model")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()

    @field_validator("openrouter_api_key")
    @classmethod
    def _blank_key_is_none(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None or not value.get_secret_value().strip():
            return None
        key = value.get_secret_value().strip()
        if len(key) > MAX_API_KEY_LENGTH:
            raise ValueError(f"The API key is longer than {MAX_API_KEY_LENGTH} characters")
        return SecretStr(key)

    @field_validator("sponsorblock_categories", mode="before")
    @classmethod
    def _split_categories(cls, value: Any) -> Any:
        # The environment variable is comma-separated.
        return value.split(",") if isinstance(value, str) else value

    @field_validator("sponsorblock_categories")
    @classmethod
    def _known_categories(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        categories = tuple(dict.fromkeys(c.strip() for c in value if c.strip()))
        unknown = set(categories) - SPONSORBLOCK_CATEGORIES
        if unknown:
            raise ValueError(f"Unknown SponsorBlock categories: {', '.join(sorted(unknown))}")
        return categories

    @field_validator("ytdlp_cookies_from_browser")
    @classmethod
    def _known_browser(cls, value: str | None) -> str | None:
        value = (value or "").strip() or None
        if value is not None:
            parse_browser_spec(value)
        return value

    def __hash__(self) -> int:
        # Frozen, so what depends on the settings can be cached by them (pydantic does
        # this too, but type checkers don't know).
        return hash(tuple(self.__dict__.values()))

    @property
    def tz(self) -> tzinfo | None:
        """The time zone "local" times and dates are in; None is the system's (what
        `datetime.astimezone()` uses)."""
        return ZoneInfo(self.timezone) if self.timezone else None


USER_SETTING_KEYS: tuple[UserSettingKey, ...] = get_args(UserSettingKey.__value__)


@dataclass(frozen=True)
class UserSettingsState:
    """Effective values, what they'd be without stored values, and where each comes from."""

    values: UserSettings
    defaults: UserSettings
    sources: dict[UserSettingKey, SettingSource]


def default_user_settings(settings: Settings | None = None) -> UserSettings:
    """The user settings as the environment (or the built-in defaults) has them."""
    settings = settings or get_settings()
    values: dict[str, Any] = {
        key: getattr(settings, key) for key in USER_SETTING_KEYS if key != "timezone"
    }
    return UserSettings.model_validate({**values, "timezone": None})


def get_user_settings(session: Session, settings: Settings | None = None) -> UserSettings:
    """The effective user settings: stored values over `default_user_settings`."""
    return describe_user_settings(session, settings).values


def load_user_settings(
    sessions: sessionmaker[Session] | None = None, settings: Settings | None = None
) -> UserSettings:
    """`get_user_settings` in a session of its own."""
    with (sessions or get_session_factory())() as session:
        return get_user_settings(session, settings)


def describe_user_settings(session: Session, settings: Settings | None = None) -> UserSettingsState:
    """Effective values, defaults and the source of each setting."""
    settings = settings or get_settings()
    defaults = default_user_settings(settings)
    values = dict(defaults)
    sources: dict[UserSettingKey, SettingSource] = {
        key: "env" if key in settings.model_fields_set else "default" for key in USER_SETTING_KEYS
    }
    for key, value in _stored(session).items():
        try:
            validated = UserSettings.model_validate({**values, key: value})
        except ValidationError as error:
            logger.warning("Ignoring the stored setting %s: %s", key, error)
            continue
        values[key] = getattr(validated, key)
        sources[key] = "user"
    return UserSettingsState(UserSettings.model_validate(values), defaults, sources)


def update_user_settings(
    session: Session,
    changes: Mapping[str, Any],
    *,
    reset: Iterable[str] = (),
    settings: Settings | None = None,
) -> UserSettingsState:
    """Store `changes` (setting -> value, validated) and reset the settings in `reset` to
    their defaults, then return the new state. Raises `ValueError` (nothing is stored) for
    an unknown setting or an invalid value. The caller commits."""
    reset = set(reset)
    unknown = (set(changes) | reset) - set(USER_SETTING_KEYS)
    if unknown:
        raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}")
    both = reset & set(changes)
    if both:
        raise ValueError(f"Settings both changed and reset: {', '.join(sorted(both))}")
    state = describe_user_settings(session, settings)
    values = dict(state.values) | {key: getattr(state.defaults, key) for key in reset}
    try:
        updated = UserSettings.model_validate({**values, **changes})
    except ValidationError as error:
        raise ValueError(_validation_message(error)) from error
    _check_consistency(updated, changed=set(changes))
    if reset:
        session.execute(
            text("DELETE FROM settings WHERE key IN :keys").bindparams(
                bindparam("keys", expanding=True)
            ),
            {"keys": sorted(reset)},
        )
    for key in changes:
        session.execute(
            text(
                """
                INSERT INTO settings (key, value) VALUES (:key, :value)
                ON CONFLICT (key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                """
            ),
            {"key": key, "value": json.dumps(_json_value(updated, key))},
        )
    return describe_user_settings(session, settings)


def key_hint(key: SecretStr | None) -> str | None:
    """The last characters of an API key, to recognize it by; None without a key (or
    with one too short to show any of it)."""
    if key is None or len(key.get_secret_value()) <= 2 * KEY_HINT_LENGTH:
        return None
    return key.get_secret_value()[-KEY_HINT_LENGTH:]


def system_timezone() -> str | None:
    """The system's time zone as an IANA name, if it can be told."""
    try:
        return tzlocal.get_localzone_name()
    except Exception:  # tzlocal raises various errors on odd configurations
        logger.warning("Couldn't tell the system time zone", exc_info=True)
        return None


def _stored(session: Session) -> dict[UserSettingKey, Any]:
    rows = session.execute(
        text("SELECT key, value FROM settings WHERE key IN :keys").bindparams(
            bindparam("keys", expanding=True)
        ),
        {"keys": list(USER_SETTING_KEYS)},
    )
    return {cast(UserSettingKey, key): json.loads(value) for key, value in rows}


def _json_value(user: UserSettings, key: str) -> Any:
    if key == "openrouter_api_key":
        key_value = user.openrouter_api_key
        return None if key_value is None else key_value.get_secret_value()
    return user.model_dump(mode="json", include={key})[key]


def _check_consistency(user: UserSettings, *, changed: set[str]) -> None:
    """Checks between settings, made when one of them changes (so an inconsistent
    environment doesn't block unrelated changes)."""
    if {"feed_size", "feed_exploration_slots"} & changed and (
        user.feed_exploration_slots > user.feed_size
    ):
        raise ValueError("Exploration slots can't be more than the feed size")
    low, high = user.feed_min_duration_seconds, user.feed_max_duration_seconds
    if (
        {"feed_min_duration_seconds", "feed_max_duration_seconds"} & changed
        and low is not None
        and high is not None
        and low > high
    ):
        raise ValueError("The shortest duration can't be longer than the longest")


def _validation_message(error: ValidationError) -> str:
    """One readable line per invalid setting, e.g. "feed_size: Input should be ..."."""
    return "; ".join(
        f"{'.'.join(str(part) for part in item['loc'])}: "
        + item["msg"].removeprefix("Value error, ")
        for item in error.errors()
    )
