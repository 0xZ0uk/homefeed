"""The candidate pool: videos that may go into a feed, with where they came from.

Sources (subscriptions now; related videos, searches, ... later) call `record` with
videos already stored in `videos`. A video is recorded once per source, keeping the
first time that source saw it. Readers such as the daily feed job call
`list_candidates`, which returns each video once, attributed to the source that found
it first.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from homefeed_core.gateway.events import format_timestamp

SUBSCRIPTION = "subscription"


@dataclass(frozen=True)
class Candidate:
    video_id: str
    source: str  # e.g. "subscription"
    source_detail: str | None  # e.g. the channel id for subscriptions
    first_seen_at: str  # ISO 8601 UTC; when any source first found the video


def record(
    session: Session,
    video_ids: Iterable[str],
    *,
    source: str,
    source_detail: str | None = None,
    now: datetime | None = None,
) -> list[str]:
    """Add `video_ids` to the pool as found by `source`. Each must exist in `videos`.

    Videos this source already found keep their original `first_seen_at`. Returns the
    ids that are new to the pool (not found by any source before), in input order.
    """
    ids = list(dict.fromkeys(video_ids))
    if not ids:
        return []
    known = set(
        session.execute(
            text("SELECT DISTINCT video_id FROM candidates WHERE video_id IN :ids").bindparams(
                bindparam("ids", expanding=True)
            ),
            {"ids": ids},
        ).scalars()
    )
    seen_at = format_timestamp(now) if now is not None else None
    session.execute(
        text(
            """
            INSERT INTO candidates (video_id, source, source_detail, first_seen_at)
            VALUES (:video_id, :source, :source_detail,
                    coalesce(:seen_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))
            ON CONFLICT (video_id, source) DO NOTHING
            """
        ),
        [
            {
                "video_id": video_id,
                "source": source,
                "source_detail": source_detail,
                "seen_at": seen_at,
            }
            for video_id in ids
        ],
    )
    return [video_id for video_id in ids if video_id not in known]


def list_candidates(
    session: Session,
    *,
    since: datetime | None = None,
    source: str | None = None,
) -> list[Candidate]:
    """The pool, one entry per video, newest first.

    Each video is attributed to the source that found it first. `since` keeps videos
    first seen at or after that time; `source` keeps videos that source found (still
    attributed to whichever source was first).
    """
    rows = session.execute(
        text(
            """
            WITH ranked AS (
                SELECT video_id, source, source_detail, first_seen_at,
                       row_number() OVER (
                           PARTITION BY video_id ORDER BY first_seen_at, source
                       ) AS rank
                FROM candidates
            )
            SELECT video_id, source, source_detail, first_seen_at
            FROM ranked
            WHERE rank = 1
              AND (:since IS NULL OR first_seen_at >= :since)
              AND (:source IS NULL OR video_id IN (
                  SELECT video_id FROM candidates WHERE source = :source
              ))
            ORDER BY first_seen_at DESC, video_id
            """
        ),
        {"since": format_timestamp(since) if since else None, "source": source},
    )
    return [Candidate(*row) for row in rows]
