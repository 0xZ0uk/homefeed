"""Explicit ratings: one tier-list grade per video, stored with its numeric value."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core.grades import Grade, grade_value


@dataclass(frozen=True)
class Rating:
    video_id: str
    grade: Grade
    value: float
    rated_at: str  # ISO 8601 UTC; when the video was first rated
    updated_at: str  # ISO 8601 UTC; when the grade last changed


_COLUMNS = "video_id, grade, value, rated_at, updated_at"


def set_rating(session: Session, video_id: str, grade: Grade) -> Rating:
    """Create or update the rating for `video_id`. Keeps `rated_at` on update."""
    row = session.execute(
        text(
            f"""
            INSERT INTO ratings (video_id, grade, value) VALUES (:video_id, :grade, :value)
            ON CONFLICT (video_id) DO UPDATE SET
                grade = excluded.grade,
                value = excluded.value,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            RETURNING {_COLUMNS}
            """
        ),
        {"video_id": video_id, "grade": grade, "value": grade_value(grade)},
    ).one()
    return Rating(*row)


def get_rating(session: Session, video_id: str) -> Rating | None:
    row = session.execute(
        text(f"SELECT {_COLUMNS} FROM ratings WHERE video_id = :video_id"),
        {"video_id": video_id},
    ).one_or_none()
    return None if row is None else Rating(*row)


def delete_rating(session: Session, video_id: str) -> bool:
    """Remove the rating for `video_id`. Returns whether one existed."""
    deleted = session.execute(
        text("DELETE FROM ratings WHERE video_id = :video_id RETURNING video_id"),
        {"video_id": video_id},
    ).first()
    return deleted is not None
