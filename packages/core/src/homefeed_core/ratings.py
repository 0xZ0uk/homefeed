"""Explicit ratings: one 1 to 10 score per video, stored with its numeric value."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core.scores import check_score, is_bottom_tier, is_top_tier, score_value


@dataclass(frozen=True)
class Rating:
    video_id: str
    score: float  # 1.0 to 10.0, one decimal
    value: float
    rated_at: str  # ISO 8601 UTC; when the video was first rated
    updated_at: str  # ISO 8601 UTC; when the score last changed


_COLUMNS = "video_id, score, value, rated_at, updated_at"


def set_rating(session: Session, video_id: str, score: float) -> Rating:
    """Create or update the rating for `video_id`. Keeps `rated_at` on update. Raises
    ValueError for a score outside 1 to 10 or with more than one decimal."""
    score = check_score(score)
    row = session.execute(
        text(
            f"""
            INSERT INTO ratings (video_id, score, value) VALUES (:video_id, :score, :value)
            ON CONFLICT (video_id) DO UPDATE SET
                score = excluded.score,
                value = excluded.value,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            RETURNING {_COLUMNS}
            """
        ),
        {"video_id": video_id, "score": score, "value": score_value(score)},
    ).one()
    return Rating(*row)


def get_rating(session: Session, video_id: str) -> Rating | None:
    row = session.execute(
        text(f"SELECT {_COLUMNS} FROM ratings WHERE video_id = :video_id"),
        {"video_id": video_id},
    ).one_or_none()
    return None if row is None else Rating(*row)


def list_ratings(session: Session) -> list[Rating]:
    """Every rating, oldest first."""
    rows = session.execute(text(f"SELECT {_COLUMNS} FROM ratings ORDER BY rated_at, video_id"))
    return [Rating(*row) for row in rows]


def tier_rated_video_ids(session: Session) -> list[str]:
    """Videos rated top tier (7.0 and up) or bottom tier (4.0 and down), oldest rating
    first: the sets the ranker's similarity features compare candidates with."""
    return [
        rating.video_id
        for rating in list_ratings(session)
        if is_top_tier(rating.score) or is_bottom_tier(rating.score)
    ]


def delete_rating(session: Session, video_id: str) -> bool:
    """Remove the rating for `video_id`. Returns whether one existed."""
    deleted = session.execute(
        text("DELETE FROM ratings WHERE video_id = :video_id RETURNING video_id"),
        {"video_id": video_id},
    ).first()
    return deleted is not None
