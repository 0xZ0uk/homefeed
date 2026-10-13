"""The mechanics shared by candidate sources that search YouTube on a schedule (saved
searches, tag discovery).

`run_search` searches through the Gateway for a query and turns the results into
`candidates.FoundVideo`s, leaving out the ids it is told to skip (rated or already known
videos). A search that fails with a `GatewayError` doesn't raise: the failure is logged
and returned in the `SearchOutcome` for the caller to record (the Gateway itself already
records it in `extractor_events`), so one failing search never fails its source.
`raise_if_all_failed` is how a source fails as a whole.

Searches run again one interval after their last run, give or take `SCHEDULE_GRACE` so a
daily search runs with every daily build even if the build finished a little earlier the
day before (see `is_due`).
"""

import logging
from collections.abc import Collection, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core.candidates import FoundVideo
from homefeed_core.gateway import Gateway, GatewayError, SearchFilters

logger = logging.getLogger(__name__)

SCHEDULE_GRACE = timedelta(hours=2)


@dataclass(frozen=True)
class SearchOutcome:
    found_count: int = 0  # results the search returned, before leaving any out
    videos: list[FoundVideo] = field(default_factory=list[FoundVideo])
    error: GatewayError | None = None  # why the search failed; then `videos` is empty


def run_search(
    gateway: Gateway,
    query: str,
    filters: SearchFilters | None = None,
    *,
    limit: int,
    source_detail: str,
    skip: Collection[str] = (),
) -> SearchOutcome:
    """Search for `query` and return up to `limit` results as candidates attributed to
    `source_detail`, without the video ids in `skip`."""
    try:
        results = gateway.search(query, filters, limit=limit)
    except GatewayError as error:
        logger.warning("Search %r failed: %s", query, error)
        return SearchOutcome(error=error)
    videos = [
        FoundVideo(
            video_id=result.id,
            title=result.title,
            channel_id=result.channel_id,
            channel_title=result.channel_title,
            source_detail=source_detail,
            channel_handle=result.channel_handle,
            duration_seconds=result.duration_seconds,
            view_count=result.view_count,
            thumbnail_url=result.thumbnail_url,
            live_status=result.live_status,
        )
        for result in results
        if result.id not in skip
    ]
    return SearchOutcome(found_count=len(results), videos=videos)


def error_message(error: GatewayError) -> str:
    """What to store as a run's `last_error`."""
    return str(error) or error.kind


def raise_if_all_failed(outcomes: Sequence[SearchOutcome]) -> None:
    """Raise the last error if there were searches and every one of them failed."""
    errors = [outcome.error for outcome in outcomes if outcome.error is not None]
    if errors and len(errors) == len(outcomes):
        raise errors[-1]


def rated_video_ids(session: Session) -> set[str]:
    return set(session.execute(text("SELECT video_id FROM ratings")).scalars())


def is_due(
    last_run_at: str | None, interval: timedelta, now: datetime, *, grace: timedelta | None = None
) -> bool:
    """Whether a search that last ran at `last_run_at` (None: never) should run at `now`."""
    if last_run_at is None:
        return True
    grace = SCHEDULE_GRACE if grace is None else grace
    return parse_timestamp(last_run_at) + interval - grace <= now


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)
