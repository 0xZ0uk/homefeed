"""The watch queue: videos to watch next, in an order the user controls.

A video is queued at most once. Positions are 0-based and kept dense (0..n-1): adding,
moving and removing an item shift the items around it. Queue items carry the video's
stored metadata (title, channel, duration, ...) when `videos` has it, else `None`s; the
API stores the metadata when a video is queued.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class QueueItem:
    id: int
    video_id: str
    position: int  # 0-based; 0 is next up
    added_at: str  # ISO 8601 UTC
    title: str | None
    channel_id: str | None
    channel_title: str | None
    duration_seconds: int | None
    published_at: str | None  # ISO 8601 UTC
    thumbnail_url: str | None


_SELECT = """
    SELECT q.id, q.video_id, q.position, q.added_at, v.title, v.channel_id, c.title,
           v.duration_seconds, v.published_at, v.thumbnail_url
    FROM queue_items AS q
    LEFT JOIN videos AS v ON v.id = q.video_id
    LEFT JOIN channels AS c ON c.id = v.channel_id
"""


def list_queue(session: Session) -> list[QueueItem]:
    """The queue in order, next up first."""
    rows = session.execute(text(f"{_SELECT} ORDER BY q.position, q.id"))
    return [QueueItem(*row) for row in rows]


def get_queue_item(session: Session, item_id: int) -> QueueItem | None:
    row = session.execute(text(f"{_SELECT} WHERE q.id = :id"), {"id": item_id}).one_or_none()
    return None if row is None else QueueItem(*row)


def find_queued_video(session: Session, video_id: str) -> QueueItem | None:
    """The queue item for `video_id`, if it's queued."""
    row = session.execute(
        text(f"{_SELECT} WHERE q.video_id = :video_id"), {"video_id": video_id}
    ).one_or_none()
    return None if row is None else QueueItem(*row)


def _length(session: Session) -> int:
    return session.execute(text("SELECT count(*) FROM queue_items")).scalar_one()


def _clamp(position: int, last: int) -> int:
    return max(0, min(position, last))


def add_to_queue(
    session: Session, video_id: str, position: int | None = None
) -> tuple[QueueItem, bool]:
    """Queue `video_id` at `position` (clamped; `None` or past the end: last).

    Returns the item and whether it is new. Queueing a video again returns its existing
    item unchanged, without moving it.
    """
    existing = find_queued_video(session, video_id)
    if existing is not None:
        return existing, False
    length = _length(session)
    position = length if position is None else _clamp(position, length)
    session.execute(
        text("UPDATE queue_items SET position = position + 1 WHERE position >= :position"),
        {"position": position},
    )
    item_id = session.execute(
        text(
            "INSERT INTO queue_items (video_id, position) VALUES (:video_id, :position) "
            "RETURNING id"
        ),
        {"video_id": video_id, "position": position},
    ).scalar_one()
    item = get_queue_item(session, item_id)
    assert item is not None
    return item, True


def move_queue_item(session: Session, item_id: int, position: int) -> QueueItem | None:
    """Move an item to `position` (clamped to the queue), shifting the items between.

    Returns the moved item, or `None` if there is no such item.
    """
    current = session.execute(
        text("SELECT position FROM queue_items WHERE id = :id"), {"id": item_id}
    ).scalar_one_or_none()
    if current is None:
        return None
    position = _clamp(position, _length(session) - 1)
    if position < current:
        session.execute(
            text(
                "UPDATE queue_items SET position = position + 1 "
                "WHERE position >= :new AND position < :old"
            ),
            {"new": position, "old": current},
        )
    elif position > current:
        session.execute(
            text(
                "UPDATE queue_items SET position = position - 1 "
                "WHERE position > :old AND position <= :new"
            ),
            {"new": position, "old": current},
        )
    session.execute(
        text("UPDATE queue_items SET position = :position WHERE id = :id"),
        {"position": position, "id": item_id},
    )
    return get_queue_item(session, item_id)


def _remove_where(session: Session, condition: str, params: dict[str, object]) -> bool:
    removed = session.execute(
        text(f"DELETE FROM queue_items WHERE {condition} RETURNING position"), params
    ).scalar_one_or_none()
    if removed is None:
        return False
    session.execute(
        text("UPDATE queue_items SET position = position - 1 WHERE position > :position"),
        {"position": removed},
    )
    return True


def remove_from_queue(session: Session, item_id: int) -> bool:
    """Remove an item, closing the gap. Returns whether it existed."""
    return _remove_where(session, "id = :id", {"id": item_id})


def remove_video_from_queue(session: Session, video_id: str) -> bool:
    """Remove `video_id` from the queue (e.g. once it has been watched to the end).
    Returns whether it was queued."""
    return _remove_where(session, "video_id = :video_id", {"video_id": video_id})


def clear_queue(session: Session) -> int:
    """Empty the queue. Returns how many items were removed."""
    return len(session.execute(text("DELETE FROM queue_items RETURNING id")).all())
