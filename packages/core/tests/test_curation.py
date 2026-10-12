import time
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.curation import (
    PRIOR_VALUES,
    PRIORS,
    NotAChannelUrlError,
    get_channel,
    list_channels,
    subscribe,
    subscribed_channel_ids,
    unsubscribe,
    update_channel,
)
from homefeed_core.db import open_database
from homefeed_core.gateway import UnavailableError, UnsupportedUrlError
from homefeed_core.gateway.fake import FakeGateway, make_channel

WOOD = make_channel("UC" + "w" * 22, title="Woodworking", handle="@wood")
BIRDS = make_channel("UC" + "b" * 22, title="birds", handle="@birds")


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


@pytest.fixture
def gateway() -> FakeGateway:
    gateway = FakeGateway()
    gateway.add_channel(WOOD)
    gateway.add_channel(BIRDS)
    return gateway


def stored_channels(sessions: sessionmaker[Session]) -> list[tuple[str, str, str | None]]:
    with sessions() as session:
        rows = session.execute(text("SELECT id, title, handle FROM channels ORDER BY id"))
        return [tuple(row) for row in rows]


def test_subscribe_by_handle_url(sessions: sessionmaker[Session], gateway: FakeGateway) -> None:
    with sessions.begin() as session:
        channel, created = subscribe(session, gateway, "https://www.youtube.com/@wood")

    assert created is True
    assert channel.channel_id == WOOD.id
    assert channel.title == "Woodworking"
    assert channel.handle == "@wood"
    assert (channel.prior, channel.pinned, channel.muted) == ("neutral", False, False)
    assert channel.subscribed_at.endswith("Z")
    assert gateway.calls == [("resolve_url", "https://www.youtube.com/@wood")]
    assert stored_channels(sessions) == [(WOOD.id, "Woodworking", "@wood")]
    with sessions() as session:
        assert get_channel(session, WOOD.id) == channel
        assert subscribed_channel_ids(session) == [WOOD.id]


def test_subscribe_again_keeps_prefs_and_refreshes_channel(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        subscribe(session, gateway, f"https://www.youtube.com/channel/{WOOD.id}")
        update_channel(session, WOOD.id, prior="love", pinned=True)
    gateway.add_channel(make_channel(WOOD.id, title="Wood Shop", handle="@wood"))

    with sessions.begin() as session:
        channel, created = subscribe(session, gateway, "@wood")

    assert created is False
    assert (channel.title, channel.prior, channel.pinned) == ("Wood Shop", "love", True)
    assert stored_channels(sessions) == [(WOOD.id, "Wood Shop", "@wood")]


def test_subscribe_updates_a_channel_already_known(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        session.execute(text(f"INSERT INTO channels (id, title) VALUES ('{WOOD.id}', 'Old')"))

    with sessions.begin() as session:
        channel, created = subscribe(session, gateway, "@wood")

    assert created is True
    assert channel.title == "Woodworking"
    assert stored_channels(sessions) == [(WOOD.id, "Woodworking", "@wood")]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtube.com/playlist?list=PL0123456789",
    ],
)
def test_subscribe_rejects_non_channel_urls(
    sessions: sessionmaker[Session], gateway: FakeGateway, url: str
) -> None:
    with pytest.raises(NotAChannelUrlError), sessions.begin() as session:
        subscribe(session, gateway, url)
    assert stored_channels(sessions) == []


def test_subscribe_passes_gateway_errors_through(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with pytest.raises(UnsupportedUrlError), sessions.begin() as session:
        subscribe(session, gateway, "https://example.com/@wood")
    with pytest.raises(UnavailableError), sessions.begin() as session:
        subscribe(session, gateway, "https://www.youtube.com/@nobody")
    assert stored_channels(sessions) == []


def test_list_channels_pinned_first_then_by_title(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        subscribe(session, gateway, "@wood")
        subscribe(session, gateway, "@birds")
    with sessions() as session:
        assert [c.title for c in list_channels(session)] == ["birds", "Woodworking"]
    with sessions.begin() as session:
        update_channel(session, WOOD.id, pinned=True)
    with sessions() as session:
        assert [c.title for c in list_channels(session)] == ["Woodworking", "birds"]


def test_update_channel_changes_only_given_fields(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        before, _ = subscribe(session, gateway, "@wood")
    time.sleep(0.01)  # timestamps have millisecond resolution

    with sessions.begin() as session:
        muted = update_channel(session, WOOD.id, muted=True)
        skeptical = update_channel(session, WOOD.id, prior="skeptical")
        unchanged = update_channel(session, WOOD.id)

    assert muted is not None and (muted.prior, muted.pinned, muted.muted) == (
        "neutral",
        False,
        True,
    )
    assert skeptical is not None and (skeptical.prior, skeptical.muted) == ("skeptical", True)
    assert unchanged == skeptical
    assert skeptical.updated_at > before.updated_at
    assert skeptical.subscribed_at == before.subscribed_at


def test_update_unknown_channel_returns_none(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        assert update_channel(session, WOOD.id, pinned=True) is None


def test_unsubscribe_keeps_the_channel(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    with sessions.begin() as session:
        subscribe(session, gateway, "@wood")
        update_channel(session, WOOD.id, prior="love")
    with sessions.begin() as session:
        assert unsubscribe(session, WOOD.id) is True
        assert unsubscribe(session, WOOD.id) is False

    with sessions() as session:
        assert list_channels(session) == []
        assert get_channel(session, WOOD.id) is None
    assert stored_channels(sessions) == [(WOOD.id, "Woodworking", "@wood")]

    with sessions.begin() as session:
        channel, created = subscribe(session, gateway, "@wood")
    assert created is True and channel.prior == "neutral"


def test_priors_have_plan_values() -> None:
    assert PRIORS == ("love", "like", "neutral", "skeptical")
    assert PRIOR_VALUES == {"love": 0.8, "like": 0.4, "neutral": 0.0, "skeptical": -0.4}


def test_table_rejects_invalid_prior_and_unknown_channel(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.execute(text(f"INSERT INTO channels (id, title) VALUES ('{WOOD.id}', 'W')"))
        session.execute(
            text(f"INSERT INTO channel_prefs (channel_id, prior) VALUES ('{WOOD.id}', 'meh')")
        )
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.execute(text("INSERT INTO channel_prefs (channel_id) VALUES ('UCmissing')"))
