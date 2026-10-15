from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import open_database
from homefeed_core.gateway.fake import make_channel, make_video
from homefeed_core.videos import get_stored_video, store_video


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def test_store_video_inserts_the_video_and_its_channel(sessions: sessionmaker[Session]) -> None:
    channel = make_channel("UC" + "a" * 22, title="Woodworking", handle="@wood")
    video = make_video(
        "aaaaaaaaaaa",
        channel=channel,
        description="How to plane",
        published_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    )
    with sessions.begin() as session:
        store_video(session, video)

    with sessions() as session:
        stored = get_stored_video(session, "aaaaaaaaaaa")
        assert get_stored_video(session, "bbbbbbbbbbb") is None
    assert stored is not None
    assert (stored.title, stored.channel_title, stored.channel_handle) == (
        video.title,
        "Woodworking",
        "@wood",
    )
    assert stored.description == "How to plane"
    assert stored.duration_seconds == 600
    assert stored.published_at == "2026-01-02T03:04:05.000Z"


def test_store_video_updates_and_keeps_known_fields(sessions: sessionmaker[Session]) -> None:
    channel = make_channel("UC" + "a" * 22, title="Woodworking")
    with sessions.begin() as session:
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, 'Old title')"), {"id": channel.id}
        )
        session.execute(
            text(
                "INSERT INTO videos (id, channel_id, title, description, thumbnail_url) "
                "VALUES ('aaaaaaaaaaa', :channel, 'RSS title', 'RSS text', 'thumb.jpg')"
            ),
            {"channel": channel.id},
        )
    with sessions.begin() as session:
        store_video(session, make_video("aaaaaaaaaaa", channel=channel, title="Full title"))

    with sessions() as session:
        stored = get_stored_video(session, "aaaaaaaaaaa")
    assert stored is not None
    assert (stored.title, stored.description, stored.thumbnail_url) == (
        "Full title",
        "RSS text",
        "thumb.jpg",
    )
    assert stored.channel_title == "Woodworking"


def test_stored_video_carries_the_channels_picture_once_it_is_known(
    sessions: sessionmaker[Session],
) -> None:
    channel = make_channel("UC" + "a" * 22, title="Woodworking")
    with sessions.begin() as session:
        store_video(session, make_video("aaaaaaaaaaa", channel=channel))
    with sessions() as session:
        stored = get_stored_video(session, "aaaaaaaaaaa")
    assert stored is not None and stored.channel_thumbnail_url is None

    # A channel lookup (subscribing, its page) stores the picture; storing a video again
    # keeps it.
    with sessions.begin() as session:
        session.execute(text("UPDATE channels SET thumbnail_url = 'https://example.invalid/w.jpg'"))
        store_video(session, make_video("aaaaaaaaaaa", channel=channel, title="Planing"))
    with sessions() as session:
        stored = get_stored_video(session, "aaaaaaaaaaa")
    assert stored is not None
    assert stored.channel_thumbnail_url == "https://example.invalid/w.jpg"
