from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import curation, onboarding
from homefeed_core.db import open_database
from homefeed_core.gateway.fake import FakeGateway, make_channel


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def test_fresh_install_needs_onboarding(sessions: sessionmaker[Session]) -> None:
    with sessions() as session:
        assert onboarding.get_status(session) == onboarding.OnboardingStatus(
            completed=False, subscribed_channels=0, needed=True
        )


def test_a_subscription_means_it_is_not_needed(sessions: sessionmaker[Session]) -> None:
    channel = make_channel("UC" + "a" * 22, title="A")
    gateway = FakeGateway()
    gateway.add_channel(channel)
    with sessions.begin() as session:
        curation.subscribe(session, gateway, f"https://www.youtube.com/channel/{channel.id}")
    with sessions() as session:
        status = onboarding.get_status(session)
    assert (status.completed, status.subscribed_channels, status.needed) == (False, 1, False)


def test_complete_sets_the_flag_and_is_repeatable(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        status = onboarding.complete(session)
    assert (status.completed, status.needed) == (True, False)
    with sessions.begin() as session:
        assert onboarding.complete(session).completed
        value = session.execute(
            text("SELECT value FROM settings WHERE key = :key"), {"key": onboarding.COMPLETED_KEY}
        ).scalar_one()
    assert value == "true"
