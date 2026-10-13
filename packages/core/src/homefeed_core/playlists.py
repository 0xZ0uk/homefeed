"""Local playlists: named, ordered lists of videos kept only in this app.

A playlist has a name (unique ignoring case, surrounding whitespace trimmed) and an
optional description. Its items are videos in a chosen order: positions are 0-based
and contiguous, a video is in a playlist at most once, and adding a video appends it
unless a position is given. A video can be added before its metadata is stored (like a
rating), so an item's title, channel and thumbnail are `None` until it is.

Nothing here feeds the ranker: playlists are a library feature, not a signal.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from homefeed_core.gateway.events import format_timestamp
from homefeed_core.gateway.urls import VIDEO_ID

NAME_MAX_LENGTH = 100
DESCRIPTION_MAX_LENGTH = 1000


class DuplicatePlaylistError(ValueError):
    """Another playlist already has this name (ignoring case)."""


@dataclass(frozen=True)
class Playlist:
    id: int
    name: str
    description: str
    item_count: int
    thumbnail_url: str | None  # the first item's thumbnail, when known
    contains_video: bool | None  # whether it has the video asked about; None if not asked
    created_at: str  # ISO 8601 UTC
    updated_at: str  # ISO 8601 UTC; changes with the name, description or items


@dataclass(frozen=True)
class PlaylistItem:
    video_id: str
    position: int  # 0-based
    added_at: str  # ISO 8601 UTC
    title: str | None  # None until the video's metadata is stored
    channel_id: str | None
    channel_title: str | None
    duration_seconds: int | None
    thumbnail_url: str | None


def normalize_name(name: str) -> str:
    """`name` trimmed. Raises `ValueError` if it is blank or too long."""
    name = name.strip()
    if not name:
        raise ValueError("Playlist name must not be blank")
    if len(name) > NAME_MAX_LENGTH:
        raise ValueError(f"Playlist name must be at most {NAME_MAX_LENGTH} characters")
    return name


def normalize_description(description: str) -> str:
    description = description.strip()
    if len(description) > DESCRIPTION_MAX_LENGTH:
        raise ValueError(
            f"Playlist description must be at most {DESCRIPTION_MAX_LENGTH} characters"
        )
    return description


def check_video_id(video_id: str) -> str:
    if not VIDEO_ID.match(video_id):
        raise ValueError(f"{video_id!r} is not a YouTube video id")
    return video_id


_PLAYLIST_SELECT = """
    SELECT p.id, p.name, p.description,
           (SELECT count(*) FROM playlist_items AS i WHERE i.playlist_id = p.id),
           (SELECT v.thumbnail_url FROM playlist_items AS i
            JOIN videos AS v ON v.id = i.video_id
            WHERE i.playlist_id = p.id ORDER BY i.position LIMIT 1),
           CASE WHEN :video_id IS NULL THEN NULL ELSE EXISTS (
               SELECT 1 FROM playlist_items AS i
               WHERE i.playlist_id = p.id AND i.video_id = :video_id
           ) END,
           p.created_at, p.updated_at
    FROM playlists AS p
"""


def _playlist(row: Row) -> Playlist:
    contains = row[5]
    return Playlist(
        id=row[0],
        name=row[1],
        description=row[2],
        item_count=row[3],
        thumbnail_url=row[4],
        contains_video=None if contains is None else bool(contains),
        created_at=row[6],
        updated_at=row[7],
    )


def list_playlists(session: Session, *, video_id: str | None = None) -> list[Playlist]:
    """All playlists, alphabetically by name. With `video_id`, each says whether it
    contains that video (for an "add to playlist" menu)."""
    rows = session.execute(
        text(f"{_PLAYLIST_SELECT} ORDER BY p.name, p.id"), {"video_id": video_id}
    )
    return [_playlist(row) for row in rows]


def get_playlist(session: Session, playlist_id: int) -> Playlist | None:
    row = session.execute(
        text(f"{_PLAYLIST_SELECT} WHERE p.id = :id"), {"id": playlist_id, "video_id": None}
    ).one_or_none()
    return None if row is None else _playlist(row)


def _name_taken(session: Session, name: str, *, other_than: int | None = None) -> bool:
    row = session.execute(
        text("SELECT 1 FROM playlists WHERE name = :name AND id != coalesce(:id, -1)"),
        {"name": name, "id": other_than},
    ).first()
    return row is not None


def create_playlist(session: Session, name: str, description: str = "") -> Playlist:
    """Create an empty playlist. Raises `DuplicatePlaylistError` if the name (ignoring
    case) is taken, `ValueError` for a blank or too long name or description."""
    name = normalize_name(name)
    description = normalize_description(description)
    if _name_taken(session, name):
        raise DuplicatePlaylistError(f"A playlist named {name!r} already exists")
    playlist_id = session.execute(
        text("INSERT INTO playlists (name, description) VALUES (:name, :description) RETURNING id"),
        {"name": name, "description": description},
    ).scalar_one()
    playlist = get_playlist(session, playlist_id)
    assert playlist is not None
    return playlist


def update_playlist(
    session: Session,
    playlist_id: int,
    *,
    name: str | None = None,
    description: str | None = None,
    now: datetime | None = None,
) -> Playlist | None:
    """Rename a playlist or change its description; `None` keeps the current value.

    Returns `None` if there is no such playlist. Raises `DuplicatePlaylistError` if
    another playlist has the new name, `ValueError` for a blank or too long value.
    """
    current = get_playlist(session, playlist_id)
    if current is None:
        return None
    new_name = current.name if name is None else normalize_name(name)
    new_description = (
        current.description if description is None else normalize_description(description)
    )
    if _name_taken(session, new_name, other_than=playlist_id):
        raise DuplicatePlaylistError(f"A playlist named {new_name!r} already exists")
    session.execute(
        text(
            """
            UPDATE playlists SET name = :name, description = :description, updated_at = :now
            WHERE id = :id
            """
        ),
        {
            "id": playlist_id,
            "name": new_name,
            "description": new_description,
            "now": format_timestamp(now or datetime.now(UTC)),
        },
    )
    return get_playlist(session, playlist_id)


def delete_playlist(session: Session, playlist_id: int) -> bool:
    """Delete a playlist and its items. Returns whether it existed."""
    deleted = session.execute(
        text("DELETE FROM playlists WHERE id = :id RETURNING id"), {"id": playlist_id}
    ).first()
    return deleted is not None


def _touch(session: Session, playlist_id: int, now: datetime | None) -> None:
    session.execute(
        text("UPDATE playlists SET updated_at = :now WHERE id = :id"),
        {"id": playlist_id, "now": format_timestamp(now or datetime.now(UTC))},
    )


def _exists(session: Session, playlist_id: int) -> bool:
    row = session.execute(
        text("SELECT 1 FROM playlists WHERE id = :id"), {"id": playlist_id}
    ).first()
    return row is not None


_ITEM_SELECT = """
    SELECT i.video_id, i.position, i.added_at, v.title, v.channel_id, c.title,
           v.duration_seconds, v.thumbnail_url
    FROM playlist_items AS i
    LEFT JOIN videos AS v ON v.id = i.video_id
    LEFT JOIN channels AS c ON c.id = v.channel_id
"""


def list_items(session: Session, playlist_id: int) -> list[PlaylistItem] | None:
    """A playlist's videos in order, or `None` if there is no such playlist."""
    if not _exists(session, playlist_id):
        return None
    rows = session.execute(
        text(f"{_ITEM_SELECT} WHERE i.playlist_id = :id ORDER BY i.position"),
        {"id": playlist_id},
    )
    return [PlaylistItem(*row) for row in rows]


def _get_item(session: Session, playlist_id: int, video_id: str) -> PlaylistItem | None:
    row = session.execute(
        text(f"{_ITEM_SELECT} WHERE i.playlist_id = :id AND i.video_id = :video_id"),
        {"id": playlist_id, "video_id": video_id},
    ).one_or_none()
    return None if row is None else PlaylistItem(*row)


def _count(session: Session, playlist_id: int) -> int:
    return session.execute(
        text("SELECT count(*) FROM playlist_items WHERE playlist_id = :id"), {"id": playlist_id}
    ).scalar_one()


def _shift(session: Session, playlist_id: int, start: int, stop: int, by: int) -> None:
    """Move the items at positions `start <= position < stop` by `by`."""
    session.execute(
        text(
            """
            UPDATE playlist_items SET position = position + :by
            WHERE playlist_id = :id AND position >= :start AND position < :stop
            """
        ),
        {"id": playlist_id, "start": start, "stop": stop, "by": by},
    )


def add_item(
    session: Session,
    playlist_id: int,
    video_id: str,
    *,
    position: int | None = None,
    now: datetime | None = None,
) -> tuple[PlaylistItem, bool] | None:
    """Add a video to a playlist: at the end, or at `position` (clamped to the end).

    Returns the item and whether it is new; adding a video that is already there
    leaves it where it is. Returns `None` if there is no such playlist. Raises
    `ValueError` for something that isn't a video id or a negative position.
    """
    check_video_id(video_id)
    if position is not None and position < 0:
        raise ValueError("Position must not be negative")
    if not _exists(session, playlist_id):
        return None
    existing = _get_item(session, playlist_id, video_id)
    if existing is not None:
        return existing, False
    count = _count(session, playlist_id)
    at = count if position is None else min(position, count)
    _shift(session, playlist_id, at, count, 1)
    session.execute(
        text(
            """
            INSERT INTO playlist_items (playlist_id, video_id, position, added_at)
            VALUES (:id, :video_id, :position, :now)
            """
        ),
        {
            "id": playlist_id,
            "video_id": video_id,
            "position": at,
            "now": format_timestamp(now or datetime.now(UTC)),
        },
    )
    _touch(session, playlist_id, now)
    item = _get_item(session, playlist_id, video_id)
    assert item is not None
    return item, True


def move_item(
    session: Session,
    playlist_id: int,
    video_id: str,
    position: int,
    *,
    now: datetime | None = None,
) -> PlaylistItem | None:
    """Move a playlist's video to `position` (clamped to the last place), shifting the
    videos in between. Returns `None` if the playlist doesn't have the video. Raises
    `ValueError` for a negative position."""
    if position < 0:
        raise ValueError("Position must not be negative")
    current = _get_item(session, playlist_id, video_id)
    if current is None:
        return None
    target = min(position, _count(session, playlist_id) - 1)
    if target != current.position:
        if target < current.position:
            _shift(session, playlist_id, target, current.position, 1)
        else:
            _shift(session, playlist_id, current.position + 1, target + 1, -1)
        session.execute(
            text(
                """
                UPDATE playlist_items SET position = :position
                WHERE playlist_id = :id AND video_id = :video_id
                """
            ),
            {"id": playlist_id, "video_id": video_id, "position": target},
        )
        _touch(session, playlist_id, now)
    return _get_item(session, playlist_id, video_id)


def remove_item(
    session: Session, playlist_id: int, video_id: str, *, now: datetime | None = None
) -> bool:
    """Take a video out of a playlist, closing the gap. Returns whether it was there."""
    removed = session.execute(
        text(
            """
            DELETE FROM playlist_items WHERE playlist_id = :id AND video_id = :video_id
            RETURNING position
            """
        ),
        {"id": playlist_id, "video_id": video_id},
    ).first()
    if removed is None:
        return False
    _shift(session, playlist_id, removed[0] + 1, _count(session, playlist_id) + 1, -1)
    _touch(session, playlist_id, now)
    return True
