from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import open_database
from homefeed_core.gateway.fake import make_channel, make_video
from homefeed_core.queue import (
    add_to_queue,
    clear_queue,
    find_queued_video,
    get_queue_item,
    list_queue,
    move_queue_item,
    remove_from_queue,
    remove_video_from_queue,
)
from homefeed_core.videos import store_video


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def queued(sessions: sessionmaker[Session]) -> list[str]:
    with sessions() as session:
        items = list_queue(session)
    assert [item.position for item in items] == list(range(len(items)))
    return [item.video_id for item in items]


def fill(sessions: sessionmaker[Session], *video_ids: str) -> list[int]:
    with sessions.begin() as session:
        return [add_to_queue(session, video_id)[0].id for video_id in video_ids]


def test_add_appends_by_default(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        first, created = add_to_queue(session, "a")
        add_to_queue(session, "b")

    assert created is True
    assert first.position == 0
    assert first.added_at.endswith("Z")
    assert first.title is None and first.channel_title is None
    assert queued(sessions) == ["a", "b"]


def test_add_at_a_position_shifts_the_rest(sessions: sessionmaker[Session]) -> None:
    fill(sessions, "a", "b", "c")
    with sessions.begin() as session:
        add_to_queue(session, "front", position=0)
        add_to_queue(session, "middle", position=2)
        add_to_queue(session, "end", position=99)
        add_to_queue(session, "negative", position=-5)

    assert queued(sessions) == ["negative", "front", "a", "middle", "b", "c", "end"]


def test_adding_again_keeps_the_existing_item(sessions: sessionmaker[Session]) -> None:
    [a, _] = fill(sessions, "a", "b")
    with sessions.begin() as session:
        item, created = add_to_queue(session, "a", position=1)

    assert created is False
    assert item.id == a and item.position == 0
    assert queued(sessions) == ["a", "b"]


def test_items_carry_stored_metadata(sessions: sessionmaker[Session]) -> None:
    channel = make_channel("UC" + "w" * 22, title="Woodworking")
    with sessions.begin() as session:
        store_video(session, make_video("aaaaaaaaaaa", channel=channel, title="Planing"))
        item, _ = add_to_queue(session, "aaaaaaaaaaa")

    assert item.title == "Planing"
    assert item.channel_id == channel.id
    assert item.channel_title == "Woodworking"
    assert item.duration_seconds == 600
    assert item.published_at == "2026-01-01T00:00:00.000Z"
    with sessions() as session:
        assert find_queued_video(session, "aaaaaaaaaaa") == item
        assert find_queued_video(session, "bbbbbbbbbbb") is None


@pytest.mark.parametrize(
    ("index", "position", "expected"),
    [
        (0, 2, ["b", "c", "a", "d"]),
        (3, 0, ["d", "a", "b", "c"]),
        (1, 2, ["a", "c", "b", "d"]),
        (2, 1, ["a", "c", "b", "d"]),
        (1, 1, ["a", "b", "c", "d"]),
        (0, 99, ["b", "c", "d", "a"]),
        (3, -1, ["d", "a", "b", "c"]),
    ],
)
def test_move(
    sessions: sessionmaker[Session], index: int, position: int, expected: list[str]
) -> None:
    ids = fill(sessions, "a", "b", "c", "d")
    with sessions.begin() as session:
        moved = move_queue_item(session, ids[index], position)

    assert moved is not None
    assert moved.position == expected.index(moved.video_id)
    assert queued(sessions) == expected


def test_move_unknown_item(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        assert move_queue_item(session, 42, 0) is None


def test_remove_closes_the_gap(sessions: sessionmaker[Session]) -> None:
    [_, b, _] = fill(sessions, "a", "b", "c")
    with sessions.begin() as session:
        assert remove_from_queue(session, b) is True
        assert remove_from_queue(session, b) is False
        assert get_queue_item(session, b) is None

    assert queued(sessions) == ["a", "c"]


def test_remove_by_video(sessions: sessionmaker[Session]) -> None:
    fill(sessions, "a", "b", "c")
    with sessions.begin() as session:
        assert remove_video_from_queue(session, "a") is True
        assert remove_video_from_queue(session, "a") is False

    assert queued(sessions) == ["b", "c"]


def test_clear(sessions: sessionmaker[Session]) -> None:
    fill(sessions, "a", "b")
    with sessions.begin() as session:
        assert clear_queue(session) == 2
        assert clear_queue(session) == 0
    assert queued(sessions) == []


def test_table_queues_a_video_once(sessions: sessionmaker[Session]) -> None:
    fill(sessions, "a")
    with pytest.raises(IntegrityError), sessions.begin() as session:
        session.execute(text("INSERT INTO queue_items (video_id, position) VALUES ('a', 1)"))
