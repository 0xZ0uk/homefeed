"""Feedback on videos: "more like this" (1) and "less like this" (-1).

A quick steer given from a feed card, one signal per video, without rating it. Pressing
the signal a video already has clears it (`clear_feedback`). Feedback is not a rating: it
is not counted for the model's weight, the insights or training, and an explicit rating
always wins over it. Its one effect is on ranking, where a video with feedback and no
rating counts like a top-tier (more) or bottom-tier (less) rated one when candidates are
compared with it (see `feeds.load_rated_tiers`). The video itself is the exception for
"more": it isn't compared with itself, so it doesn't push itself up the next feed.

Unlike a rating, feedback needs a stored video: the row goes with it. Cards only show
stored videos, so the API answers a signal for an unknown one with a 404.
"""

from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

MORE = 1
LESS = -1
Signal = Literal[1, -1]
SIGNALS: tuple[Signal, ...] = (MORE, LESS)


@dataclass(frozen=True)
class Feedback:
    video_id: str
    signal: Signal  # 1: more like this, -1: less like this
    created_at: str  # ISO 8601 UTC; when the video first got feedback
    updated_at: str  # ISO 8601 UTC; when the signal last changed


_COLUMNS = "video_id, signal, created_at, updated_at"


def set_feedback(session: Session, video_id: str, signal: int) -> Feedback | None:
    """Mark `video_id` "more like this" (1) or "less like this" (-1), replacing the signal
    it had. `created_at` is kept, and `updated_at` moves only when the signal changes, so
    repeating a request changes nothing. Returns None if the video isn't stored. Raises
    ValueError for any other signal (a bool is not one)."""
    if isinstance(signal, bool) or signal not in SIGNALS:
        raise ValueError(f"Feedback {signal!r} is neither 1 (more) nor -1 (less)")
    stored = session.execute(
        text("SELECT 1 FROM videos WHERE id = :video_id"), {"video_id": video_id}
    ).first()
    if stored is None:
        return None
    session.execute(
        text(
            """
            INSERT INTO video_feedback (video_id, signal) VALUES (:video_id, :signal)
            ON CONFLICT (video_id) DO UPDATE SET
                signal = excluded.signal,
                updated_at = CASE
                    WHEN signal = excluded.signal THEN updated_at
                    ELSE strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                END
            """
        ),
        {"video_id": video_id, "signal": signal},
    )
    return get_feedback(session, video_id)


def clear_feedback(session: Session, video_id: str) -> bool:
    """Take the feedback off `video_id`. Returns whether it had any."""
    deleted = session.execute(
        text("DELETE FROM video_feedback WHERE video_id = :video_id RETURNING video_id"),
        {"video_id": video_id},
    ).first()
    return deleted is not None


def get_feedback(session: Session, video_id: str) -> Feedback | None:
    """`video_id`'s feedback, or None when it has none."""
    row = session.execute(
        text(f"SELECT {_COLUMNS} FROM video_feedback WHERE video_id = :video_id"),
        {"video_id": video_id},
    ).one_or_none()
    return None if row is None else Feedback(*row)


def list_feedback(session: Session) -> list[Feedback]:
    """Every video with feedback, the oldest first."""
    rows = session.execute(
        text(f"SELECT {_COLUMNS} FROM video_feedback ORDER BY created_at, video_id")
    )
    return [Feedback(*row) for row in rows]
