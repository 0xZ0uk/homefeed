"""Watch events: how a video was watched, as reported by the player.

Each event is a type (`play`, `pause`, `seeked`, `ended`, `close`), the playback position
and the video's duration (both in seconds), stamped with the time it was recorded.

Derived facts:
- Watched: the video has a `play` event (the player never autoplays, so playing is a
  choice). Opening the watch page without pressing play doesn't count. The feed's
  "already watched" filter also counts rated videos (see `feeds.watched_video_ids`).
- Abandoned early: played, never reached the end (no `ended` event), and the furthest
  position recorded is under `ABANDON_SECONDS` (60). Seeking ahead counts as reaching
  that point. Whether a rating overrides the signal is the trainer's call (PLAN.md
  section 7: rated videos ignore implicit signals).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, get_args

from sqlalchemy import text
from sqlalchemy.orm import Session

WatchEventType = Literal["play", "pause", "seeked", "ended", "close"]
WATCH_EVENT_TYPES: tuple[WatchEventType, ...] = get_args(WatchEventType)

# Leaving within this many seconds of the start is a weak negative signal.
ABANDON_SECONDS = 60.0


@dataclass(frozen=True)
class WatchEvent:
    id: int
    video_id: str
    event_type: WatchEventType
    position: float  # seconds into the video
    duration: float | None  # seconds; None while unknown
    at: str  # ISO 8601 UTC; when the event was recorded


_COLUMNS = "id, video_id, event_type, position, duration, at"


def record_watch_event(
    session: Session,
    video_id: str,
    event_type: WatchEventType,
    position: float,
    duration: float | None = None,
    *,
    at: str | None = None,
) -> WatchEvent:
    """Store one event. `at` (ISO 8601 UTC) defaults to now. The caller commits."""
    if event_type not in WATCH_EVENT_TYPES:
        raise ValueError(f"Unknown watch event type {event_type!r}")
    row = session.execute(
        text(
            f"""
            INSERT INTO watch_events (video_id, event_type, position, duration, at)
            VALUES (:video_id, :event_type, :position, :duration,
                    coalesce(:at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))
            RETURNING {_COLUMNS}
            """
        ),
        {
            "video_id": video_id,
            "event_type": event_type,
            "position": position,
            "duration": duration,
            "at": at,
        },
    ).one()
    return WatchEvent(*row)


def list_watch_events(session: Session, video_id: str) -> list[WatchEvent]:
    """A video's events, oldest first."""
    rows = session.execute(
        text(f"SELECT {_COLUMNS} FROM watch_events WHERE video_id = :video_id ORDER BY at, id"),
        {"video_id": video_id},
    )
    return [WatchEvent(*row) for row in rows]


def played_video_ids(session: Session) -> set[str]:
    """Videos with at least one `play` event."""
    return set(
        session.execute(
            text("SELECT DISTINCT video_id FROM watch_events WHERE event_type = 'play'")
        ).scalars()
    )


def is_abandoned_early(events: Sequence[WatchEvent], *, threshold: float = ABANDON_SECONDS) -> bool:
    """Whether these events (one video's) show it was played and left before `threshold`
    seconds: a `play`, no `ended`, and every recorded position under `threshold`."""
    types = {event.event_type for event in events}
    if "play" not in types or "ended" in types:
        return False
    return max(event.position for event in events) < threshold


def abandoned_early(session: Session, video_id: str, *, threshold: float = ABANDON_SECONDS) -> bool:
    """Whether `video_id` was played and left within `threshold` seconds."""
    return is_abandoned_early(list_watch_events(session, video_id), threshold=threshold)


def abandoned_early_video_ids(session: Session, *, threshold: float = ABANDON_SECONDS) -> set[str]:
    """All videos played and left within `threshold` seconds (for the trainer's implicit
    negatives). Same rule as `is_abandoned_early`."""
    return set(
        session.execute(
            text(
                """
                SELECT video_id FROM watch_events
                GROUP BY video_id
                HAVING max(event_type = 'play') = 1
                   AND max(event_type = 'ended') = 0
                   AND max(position) < :threshold
                """
            ),
            {"threshold": threshold},
        ).scalars()
    )
