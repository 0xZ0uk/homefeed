import json
from collections.abc import Iterator
from datetime import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.config import Settings
from homefeed_core.db import open_database
from homefeed_core.exporter import export_data
from homefeed_core.user_settings import (
    USER_SETTING_KEYS,
    UserSettings,
    default_user_settings,
    describe_user_settings,
    get_user_settings,
    key_hint,
    update_user_settings,
)

# What an existing install might have in `.env`.
ENV = Settings(
    feed_size=12,
    feed_refresh_time=time(7, 30),
    llm_provider="ollama",
    openrouter_api_key=SecretStr("sk-or-from-env-1234"),
    sponsorblock_categories="sponsor, intro",
)


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def update(
    sessions: sessionmaker[Session],
    changes: dict[str, Any] | None = None,
    *,
    reset: list[str] | None = None,
    settings: Settings = ENV,
) -> UserSettings:
    with sessions.begin() as session:
        return update_user_settings(
            session, changes or {}, reset=reset or [], settings=settings
        ).values


def effective(sessions: sessionmaker[Session], settings: Settings = ENV) -> UserSettings:
    with sessions() as session:
        return get_user_settings(session, settings)


def stored(sessions: sessionmaker[Session]) -> dict[str, Any]:
    with sessions() as session:
        rows = session.execute(text("SELECT key, value FROM settings"))
        return {key: json.loads(value) for key, value in rows}


def test_keys_match_the_model() -> None:
    assert USER_SETTING_KEYS == tuple(UserSettings.model_fields)


def test_built_in_defaults_without_environment_or_stored_values(
    sessions: sessionmaker[Session],
) -> None:
    built_in = Settings()

    with sessions() as session:
        state = describe_user_settings(session, built_in)

    assert state.values == state.defaults
    assert state.values.feed_size == built_in.feed_size
    assert state.values.feed_refresh_time == time(6, 0)
    assert state.values.timezone is None and state.values.tz is None
    assert state.values.sponsorblock_categories == ("sponsor", "selfpromo", "interaction")
    assert set(state.sources.values()) == {"default"}


def test_environment_values_apply_until_changed(sessions: sessionmaker[Session]) -> None:
    """Backward compatibility: with nothing stored, `.env` decides, as before."""
    with sessions() as session:
        state = describe_user_settings(session, ENV)

    assert state.values == default_user_settings(ENV)
    assert state.values.feed_size == 12
    assert state.values.feed_refresh_time == time(7, 30)
    assert state.values.llm_provider == "ollama"
    assert state.values.sponsorblock_categories == ("sponsor", "intro")
    assert state.sources["feed_size"] == "env"
    assert state.sources["feed_exploration_slots"] == "default"


def test_stored_values_override_and_reset_goes_back_to_the_environment(
    sessions: sessionmaker[Session],
) -> None:
    values = update(sessions, {"feed_size": 30, "feed_refresh_time": "05:15"})

    assert values.feed_size == 30
    assert values.feed_refresh_time == time(5, 15)
    assert stored(sessions) == {"feed_size": 30, "feed_refresh_time": "05:15:00"}
    with sessions() as session:
        assert describe_user_settings(session, ENV).sources["feed_size"] == "user"

    values = update(sessions, reset=["feed_size"])

    assert values.feed_size == 12
    assert values.feed_refresh_time == time(5, 15)
    assert stored(sessions) == {"feed_refresh_time": "05:15:00"}
    with sessions() as session:
        assert describe_user_settings(session, ENV).sources["feed_size"] == "env"


def test_stored_values_apply_over_any_environment(sessions: sessionmaker[Session]) -> None:
    update(sessions, {"llm_provider": "none"})

    assert effective(sessions, Settings(llm_provider="openrouter")).llm_provider == "none"


def test_a_value_like_the_default_is_still_stored(sessions: sessionmaker[Session]) -> None:
    update(sessions, {"feed_size": 12})

    assert stored(sessions) == {"feed_size": 12}  # so a later .env change doesn't move it


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"feed_size": 0}, "feed_size"),
        ({"feed_size": 1_000}, "feed_size"),
        ({"feed_exploration_slots": -1}, "feed_exploration_slots"),
        ({"feed_min_duration_seconds": -5}, "feed_min_duration_seconds"),
        ({"feed_refresh_time": "25:00"}, "feed_refresh_time"),
        ({"model_training_time": "soon"}, "model_training_time"),
        ({"timezone": "Mars/Olympus_Mons"}, "Unknown time zone"),
        ({"timezone": "../etc/passwd"}, "Unknown time zone"),
        ({"llm_provider": "openai"}, "llm_provider"),
        ({"llm_model": "x" * 201}, "llm_model"),
        ({"llm_max_tags_per_run": -1}, "llm_max_tags_per_run"),
        ({"tag_discovery_per_day": -1}, "tag_discovery_per_day"),
        ({"sponsorblock_categories": ["sponsor", "ads"]}, "Unknown SponsorBlock categories: ads"),
        ({"feed_exploration_slots": 21}, "more than the feed size"),
        (
            {"feed_min_duration_seconds": 600, "feed_max_duration_seconds": 60},
            "shortest duration",
        ),
        ({"theme": "dark"}, "Unknown settings: theme"),
    ],
)
def test_invalid_values_are_rejected_and_nothing_is_stored(
    sessions: sessionmaker[Session], changes: dict[str, Any], message: str
) -> None:
    update(sessions, {"feed_size": 20})

    with pytest.raises(ValueError, match=message):
        update(sessions, changes)

    assert stored(sessions) == {"feed_size": 20}


def test_an_update_is_all_or_nothing(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(ValueError, match="feed_size"):
        update(sessions, {"llm_model": "valid/model", "feed_size": -1}, reset=["timezone"])

    assert stored(sessions) == {}


def test_unknown_reset_and_set_with_reset_are_rejected(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(ValueError, match="Unknown settings"):
        update(sessions, reset=["nope"])
    with pytest.raises(ValueError, match="both changed and reset"):
        update(sessions, {"feed_size": 5}, reset=["feed_size"])


def test_cross_checks_only_apply_to_what_changes(sessions: sessionmaker[Session]) -> None:
    """An inconsistent environment doesn't block unrelated changes."""
    inconsistent = Settings(feed_size=2, feed_exploration_slots=3)

    assert update(sessions, {"llm_model": "m"}, settings=inconsistent).llm_model == "m"
    with pytest.raises(ValueError, match="more than the feed size"):
        update(sessions, {"feed_size": 1}, settings=inconsistent)


def test_values_are_normalized(sessions: sessionmaker[Session]) -> None:
    values = update(
        sessions,
        {
            "feed_refresh_time": "06:30:45",
            "timezone": " Europe/Lisbon ",
            "llm_model": "  google/gemini-2.5-flash-lite ",
            "sponsorblock_categories": ["filler", "sponsor", "filler"],
        },
    )

    assert values.feed_refresh_time == time(6, 30)
    assert values.timezone == "Europe/Lisbon"
    assert values.tz == ZoneInfo("Europe/Lisbon")
    assert values.llm_model == "google/gemini-2.5-flash-lite"
    assert values.sponsorblock_categories == ("filler", "sponsor")


def test_nullable_values_can_be_set_to_null(sessions: sessionmaker[Session]) -> None:
    env = Settings(feed_min_duration_seconds=60)

    values = update(sessions, {"feed_min_duration_seconds": None}, settings=env)

    assert values.feed_min_duration_seconds is None
    assert stored(sessions) == {"feed_min_duration_seconds": None}


def test_an_invalid_stored_value_falls_back_to_the_default(
    sessions: sessionmaker[Session], caplog: pytest.LogCaptureFixture
) -> None:
    with sessions.begin() as session:
        session.execute(
            text(
                "INSERT INTO settings (key, value) VALUES "
                "('feed_size', '\"lots\"'), ('timezone', '\"Nowhere/Land\"'), "
                "('model_training_time', '\"02:00:00\"'), ('theme', '\"dark\"')"
            )
        )

    with sessions() as session:
        state = describe_user_settings(session, ENV)

    assert state.values.feed_size == 12 and state.sources["feed_size"] == "env"
    assert state.values.timezone is None
    assert state.values.model_training_time == time(2, 0)  # the valid one applies
    assert "Ignoring the stored setting feed_size" in caplog.text


# The OpenRouter API key


def test_api_key_is_stored_and_can_be_cleared(sessions: sessionmaker[Session]) -> None:
    values = update(sessions, {"openrouter_api_key": "  sk-or-v1-abcdef9876 "})

    assert values.openrouter_api_key == SecretStr("sk-or-v1-abcdef9876")
    assert stored(sessions) == {"openrouter_api_key": "sk-or-v1-abcdef9876"}  # plain text
    assert key_hint(values.openrouter_api_key) == "9876"

    # An empty key turns it off, whatever the environment has.
    assert update(sessions, {"openrouter_api_key": ""}).openrouter_api_key is None
    # Resetting goes back to the environment's.
    values = update(sessions, reset=["openrouter_api_key"])
    assert key_hint(values.openrouter_api_key) == "1234"
    assert key_hint(None) is None
    assert key_hint(SecretStr("sk-12345")) is None  # too short to show any of it


def test_api_key_is_not_in_the_model_dump(sessions: sessionmaker[Session]) -> None:
    values = update(sessions, {"openrouter_api_key": "sk-or-secret"})

    assert "sk-or-secret" not in values.model_dump_json()
    assert "sk-or-secret" not in repr(values)


def test_export_leaves_the_api_key_out(sessions: sessionmaker[Session]) -> None:
    update(sessions, {"openrouter_api_key": "sk-or-secret", "feed_size": 9})

    with sessions() as session:
        data = export_data(session)

    assert data["settings"]["stored"] == {"feed_size": 9}
    assert "sk-or-secret" not in json.dumps(data)
