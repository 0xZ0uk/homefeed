from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import open_database
from homefeed_core.gateway.fake import make_channel, make_video
from homefeed_core.playlists import (
    DuplicatePlaylistError,
    add_item,
    create_playlist,
    delete_playlist,
    get_playlist,
    list_items,
    list_playlists,
    move_item,
    remove_item,
    update_playlist,
)
from homefeed_core.videos import store_video

T0 = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
A, B, C, D = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"
WOOD = make_channel("UC" + "w" * 22, title="Wood")


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


@pytest.fixture
def session(sessions: sessionmaker[Session]) -> Iterator[Session]:
    with sessions.begin() as session:
        yield session


def order(session: Session, playlist_id: int) -> list[str]:
    items = list_items(session, playlist_id)
    assert items is not None
    assert [item.position for item in items] == list(range(len(items)))
    return [item.video_id for item in items]


def filled(session: Session, *video_ids: str) -> int:
    playlist = create_playlist(session, "Watch later")
    for video_id in video_ids:
        assert add_item(session, playlist.id, video_id) is not None
    return playlist.id


# Playlists


def test_create_and_list_alphabetically(session: Session) -> None:
    later = create_playlist(session, "  watch later ", "for the weekend")
    create_playlist(session, "Blacksmithing")

    assert later.name == "watch later"
    assert later.description == "for the weekend"
    assert later.item_count == 0
    assert later.thumbnail_url is None
    assert later.contains_video is None
    assert later.created_at == later.updated_at
    assert [p.name for p in list_playlists(session)] == ["Blacksmithing", "watch later"]


@pytest.mark.parametrize("name", ["", "   ", "x" * 101])
def test_rejects_blank_or_long_names(session: Session, name: str) -> None:
    with pytest.raises(ValueError):
        create_playlist(session, name)


def test_names_are_unique_ignoring_case(session: Session) -> None:
    create_playlist(session, "Watch later")

    with pytest.raises(DuplicatePlaylistError):
        create_playlist(session, "WATCH LATER")


def test_database_rejects_duplicate_names(session: Session) -> None:
    create_playlist(session, "Watch later")

    with pytest.raises(IntegrityError):
        session.execute(text("INSERT INTO playlists (name) VALUES ('watch LATER')"))


def test_update_renames_and_redescribes(session: Session) -> None:
    playlist = create_playlist(session, "Later", "old")

    renamed = update_playlist(session, playlist.id, name="Weekend", now=T0)
    assert renamed is not None
    assert (renamed.name, renamed.description) == ("Weekend", "old")
    assert renamed.updated_at == "2026-10-12T06:00:00.000Z"

    described = update_playlist(session, playlist.id, description="new")
    assert described is not None
    assert (described.name, described.description) == ("Weekend", "new")


def test_update_can_change_the_case_of_its_own_name(session: Session) -> None:
    playlist = create_playlist(session, "later")

    renamed = update_playlist(session, playlist.id, name="Later")

    assert renamed is not None and renamed.name == "Later"


def test_update_rejects_another_playlists_name(session: Session) -> None:
    create_playlist(session, "Weekend")
    playlist = create_playlist(session, "Later")

    with pytest.raises(DuplicatePlaylistError):
        update_playlist(session, playlist.id, name="weekend")


def test_update_and_delete_missing_playlist(session: Session) -> None:
    assert update_playlist(session, 99, name="x") is None
    assert delete_playlist(session, 99) is False


def test_delete_removes_items(session: Session) -> None:
    playlist_id = filled(session, A, B)

    assert delete_playlist(session, playlist_id) is True

    assert get_playlist(session, playlist_id) is None
    assert session.execute(text("SELECT count(*) FROM playlist_items")).scalar_one() == 0


# Items


def test_add_appends_and_is_idempotent(session: Session) -> None:
    playlist_id = filled(session, A, B)

    result = add_item(session, playlist_id, A)

    assert result is not None
    item, created = result
    assert (item.video_id, item.position, created) == (A, 0, False)
    assert order(session, playlist_id) == [A, B]


def test_add_at_a_position_shifts_the_rest(session: Session) -> None:
    playlist_id = filled(session, A, B)

    add_item(session, playlist_id, C, position=1)
    add_item(session, playlist_id, D, position=50)

    assert order(session, playlist_id) == [A, C, B, D]


def test_add_rejects_bad_ids_and_positions(session: Session) -> None:
    playlist_id = filled(session)

    with pytest.raises(ValueError):
        add_item(session, playlist_id, "not-an-id")
    with pytest.raises(ValueError):
        add_item(session, playlist_id, A, position=-1)


def test_add_to_missing_playlist(session: Session) -> None:
    assert add_item(session, 99, A) is None
    assert list_items(session, 99) is None


def test_items_show_stored_metadata(session: Session) -> None:
    store_video(session, make_video(A, channel=WOOD, title="Hand planes", duration_seconds=600))
    playlist_id = filled(session, B, A)

    items = list_items(session, playlist_id)

    assert items is not None
    known = items[1]
    assert (known.title, known.channel_title, known.duration_seconds) == (
        "Hand planes",
        "Wood",
        600,
    )
    assert known.channel_id == WOOD.id
    assert items[0].title is None and items[0].thumbnail_url is None


def test_playlist_counts_items_and_uses_first_thumbnail(session: Session) -> None:
    store_video(session, make_video(A, channel=WOOD, thumbnail_url="https://i.ytimg.com/a.jpg"))
    playlist_id = filled(session, A, B)

    playlist = get_playlist(session, playlist_id)

    assert playlist is not None
    assert playlist.item_count == 2
    assert playlist.thumbnail_url == "https://i.ytimg.com/a.jpg"


def test_list_says_which_playlists_contain_a_video(session: Session) -> None:
    with_a = filled(session, A)
    create_playlist(session, "Empty")

    found = {p.id: p.contains_video for p in list_playlists(session, video_id=A)}

    assert found[with_a] is True
    assert sorted(found.values(), key=bool) == [False, True]


@pytest.mark.parametrize(
    ("video_id", "position", "expected"),
    [
        (A, 2, [B, C, A, D]),
        (D, 0, [D, A, B, C]),
        (B, 99, [A, C, D, B]),
        (C, 2, [A, B, C, D]),
    ],
)
def test_move_shifts_the_videos_in_between(
    session: Session, video_id: str, position: int, expected: list[str]
) -> None:
    playlist_id = filled(session, A, B, C, D)

    moved = move_item(session, playlist_id, video_id, position)

    assert moved is not None
    assert moved.position == expected.index(video_id)
    assert order(session, playlist_id) == expected


def test_move_missing_item(session: Session) -> None:
    playlist_id = filled(session, A)

    assert move_item(session, playlist_id, B, 0) is None
    with pytest.raises(ValueError):
        move_item(session, playlist_id, A, -1)


def test_remove_closes_the_gap(session: Session) -> None:
    playlist_id = filled(session, A, B, C)

    assert remove_item(session, playlist_id, B, now=T0) is True
    assert remove_item(session, playlist_id, B) is False

    assert order(session, playlist_id) == [A, C]
    playlist = get_playlist(session, playlist_id)
    assert playlist is not None and playlist.updated_at == "2026-10-12T06:00:00.000Z"
