"""Watch history: the videos I've played, newest first, searchable, with where I left off.

Built from `watch_events` (see `homefeed_core.watch_events`); there is no separate table.
A video is in the history once it has a `play` event, like `played_video_ids`. Its
details come from the stored `videos` row when there is one (the watch page stores it),
so a video watched while YouTube was unreachable may have no title.

Resume position: where the last recorded event left playback, unless that was the end
(an `ended` event, or within `RESUME_END_MARGIN` seconds of the duration) or barely past
the start (under `RESUME_MIN_SECONDS`). Then the video starts from the beginning. A
`close` that near the start is skipped when finding the last event: it's a visit that
ended before playback got anywhere (e.g. leaving before the player loaded), and shouldn't
lose the earlier position.

Search matches every word of the query, case-insensitively, against the video title and
the channel title. Filtering happens in Python (`str.casefold`) rather than SQLite's
`LIKE`, which only folds ASCII case; one person's history is small enough for that.
"""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

# Resuming within this many seconds of the start isn't worth it: start over.
RESUME_MIN_SECONDS = 5.0
# Stopping within this many seconds of the end counts as finished: start over.
RESUME_END_MARGIN = 10.0

DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 200
HISTORY_QUERY_MAX_LENGTH = 200


@dataclass(frozen=True)
class HistoryEntry:
    video_id: str
    title: str | None  # None when the video's details were never stored
    channel_id: str | None
    channel_title: str | None
    thumbnail_url: str | None
    duration: float | None  # seconds; the stored duration, else the player's
    first_watched_at: str  # ISO 8601 UTC; the first event recorded for the video
    last_watched_at: str  # ISO 8601 UTC; the latest event recorded for the video
    position: float  # seconds; where the latest event left playback
    finished: bool  # played to the end at least once
    resume_position: float | None  # seconds; None to start from the beginning
    score: float | None  # the video's rating, if any


def resume_position(last_event_type: str, position: float, duration: float | None) -> float | None:
    """Where to resume, given the latest event, or None to start from the beginning."""
    if last_event_type == "ended" or position < RESUME_MIN_SECONDS:
        return None
    if duration is not None and position >= duration - RESUME_END_MARGIN:
        return None
    return position


_QUERY = """
    WITH watched AS (
        SELECT video_id, min(at) AS first_at, max(at) AS last_at, max(id) AS last_id,
               max(event_type = 'ended') AS finished
        FROM watch_events
        {where}
        GROUP BY video_id
        HAVING max(event_type = 'play') = 1
    ),
    latest AS (
        SELECT video_id, event_type, position, duration FROM (
            SELECT video_id, event_type, position, duration,
                   row_number() OVER (PARTITION BY video_id ORDER BY at DESC, id DESC) AS n
            FROM watch_events
            WHERE video_id IN (SELECT video_id FROM watched)
              AND NOT (event_type = 'close' AND position < :min_seconds)
        )
        WHERE n = 1
    )
    SELECT w.video_id, v.title, v.channel_id, c.title, v.thumbnail_url,
           coalesce(v.duration_seconds, l.duration), w.first_at, w.last_at,
           l.position, w.finished, l.event_type, l.duration, r.score
    FROM watched AS w
    JOIN latest AS l ON l.video_id = w.video_id
    LEFT JOIN videos AS v ON v.id = w.video_id
    LEFT JOIN channels AS c ON c.id = v.channel_id
    LEFT JOIN ratings AS r ON r.video_id = w.video_id
    ORDER BY w.last_at DESC, w.last_id DESC
"""


def _entries(session: Session, video_id: str | None = None) -> list[HistoryEntry]:
    where = "" if video_id is None else "WHERE video_id = :video_id"
    rows = session.execute(
        text(_QUERY.format(where=where)),
        {"video_id": video_id, "min_seconds": RESUME_MIN_SECONDS},
    )
    entries = []
    for (
        vid,
        title,
        channel_id,
        channel_title,
        thumbnail_url,
        duration,
        first_at,
        last_at,
        position,
        finished,
        last_type,
        last_duration,
        score,
    ) in rows:
        entries.append(
            HistoryEntry(
                video_id=vid,
                title=title,
                channel_id=channel_id,
                channel_title=channel_title,
                thumbnail_url=thumbnail_url,
                duration=None if duration is None else float(duration),
                first_watched_at=first_at,
                last_watched_at=last_at,
                position=position,
                finished=bool(finished),
                resume_position=resume_position(
                    last_type, position, duration if duration is not None else last_duration
                ),
                score=score,
            )
        )
    return entries


def _matches(entry: HistoryEntry, terms: list[str]) -> bool:
    haystack = f"{entry.title or ''}\n{entry.channel_title or ''}".casefold()
    return all(term in haystack for term in terms)


def search_history(
    session: Session,
    query: str | None = None,
    *,
    limit: int = DEFAULT_HISTORY_LIMIT,
    offset: int = 0,
) -> list[HistoryEntry]:
    """Watched videos, most recently watched first, optionally only those whose title or
    channel contains every word of `query` (case-insensitive)."""
    entries = _entries(session)
    terms = (query or "").casefold().split()
    if terms:
        entries = [entry for entry in entries if _matches(entry, terms)]
    return entries[offset : offset + limit]


def get_history_entry(session: Session, video_id: str) -> HistoryEntry | None:
    """`video_id`'s history entry (with its resume position), or None if never played."""
    entries = _entries(session, video_id)
    return entries[0] if entries else None
