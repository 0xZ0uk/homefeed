"""Saved searches: YouTube searches whose results become candidates on a schedule.

A saved search is a query plus YouTube's search filters (`gateway.SearchFilters`) and a
schedule: `daily`, `weekly` or `paused`. The same query (ignoring case) with the same
filters is saved once.

`SavedSearchSource` is the `candidates.CandidateSource` that runs them: each time the
candidate sources run (with the daily feed build), every saved search that is due is
searched and its top `per_search` results are recorded as candidates from source
`saved_search`, with the query as `source_detail` (for "From your 'woodworking'
search"). A search is due when it never ran, or when its schedule's interval has passed
since its last run, give or take `SCHEDULE_GRACE` so a daily search runs with every
daily build even if the build finished a little earlier the day before. Changing a
search's query or filters makes it due again.
"""

import json
import logging
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, cast, get_args

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.candidates import SAVED_SEARCH, FoundVideo
from homefeed_core.gateway import (
    Gateway,
    GatewayError,
    SearchFilters,
    normalize_search_query,
)
from homefeed_core.gateway.events import format_timestamp

logger = logging.getLogger(__name__)

Schedule = Literal["daily", "weekly", "paused"]

SCHEDULES: tuple[Schedule, ...] = get_args(Schedule)
DEFAULT_SCHEDULE: Schedule = "daily"
SCHEDULE_INTERVALS: dict[Schedule, timedelta] = {
    "daily": timedelta(days=1),
    "weekly": timedelta(days=7),
}
SCHEDULE_GRACE = timedelta(hours=2)
# How many of each search's top results become candidates per run.
DEFAULT_RESULTS_PER_SEARCH = 10


class DuplicateSavedSearchError(ValueError):
    """Another saved search has this query (ignoring case) and these filters."""


@dataclass(frozen=True)
class SavedSearch:
    id: int
    query: str
    filters: SearchFilters
    schedule: Schedule
    next_run_at: str | None  # ISO 8601 UTC; None while paused. In the past: due now.
    last_run_at: str | None  # ISO 8601 UTC; None if it never ran
    last_found_count: int | None  # results found by the last successful run
    last_error: str | None  # why the last run failed; None after a success
    created_at: str
    updated_at: str


def encode_filters(filters: SearchFilters) -> str:
    """Canonical JSON with only the non-default filters ("{}" for a plain search)."""
    defaults = asdict(SearchFilters())
    changed = {key: value for key, value in asdict(filters).items() if value != defaults[key]}
    return json.dumps(changed, sort_keys=True, separators=(",", ":"))


def decode_filters(value: str) -> SearchFilters:
    raw = json.loads(value)
    if not isinstance(raw, dict):
        return SearchFilters()
    known = {name: raw[name] for name in asdict(SearchFilters()) if name in raw}
    return SearchFilters(**cast(dict[str, Any], known))


def _check_schedule(schedule: str) -> Schedule:
    if schedule not in SCHEDULES:
        raise ValueError(f"Schedule must be one of {', '.join(SCHEDULES)}")
    return cast(Schedule, schedule)


_COLUMNS = (
    "id, query, filters, schedule, last_run_at, last_found_count, last_error, "
    "created_at, updated_at"
)


def list_saved_searches(session: Session) -> list[SavedSearch]:
    """All saved searches, alphabetically by query."""
    rows = session.execute(
        text(f"SELECT {_COLUMNS} FROM saved_searches ORDER BY query, filters, id")
    )
    return [_saved_search(row) for row in rows]


def get_saved_search(session: Session, search_id: int) -> SavedSearch | None:
    row = session.execute(
        text(f"SELECT {_COLUMNS} FROM saved_searches WHERE id = :id"), {"id": search_id}
    ).one_or_none()
    return None if row is None else _saved_search(row)


def add_saved_search(
    session: Session,
    query: str,
    filters: SearchFilters | None = None,
    *,
    schedule: Schedule = DEFAULT_SCHEDULE,
) -> tuple[SavedSearch, bool]:
    """Save a search (query normalized with `gateway.normalize_search_query`).

    Returns the search and whether it is new; saving the same query (in any case) with
    the same filters again returns the existing one unchanged. Raises `ValueError` for a
    blank or too long query or an unknown schedule.
    """
    query = normalize_search_query(query)
    encoded = encode_filters(filters or SearchFilters())
    row = session.execute(
        text(
            f"""
            INSERT INTO saved_searches (query, filters, schedule)
            VALUES (:query, :filters, :schedule)
            ON CONFLICT (query, filters) DO NOTHING
            RETURNING {_COLUMNS}
            """
        ),
        {"query": query, "filters": encoded, "schedule": _check_schedule(schedule)},
    ).one_or_none()
    if row is not None:
        return _saved_search(row), True
    existing = session.execute(
        text(f"SELECT {_COLUMNS} FROM saved_searches WHERE query = :query AND filters = :filters"),
        {"query": query, "filters": encoded},
    ).one()
    return _saved_search(existing), False


def update_saved_search(
    session: Session,
    search_id: int,
    *,
    query: str | None = None,
    filters: SearchFilters | None = None,
    schedule: Schedule | None = None,
    now: datetime | None = None,
) -> SavedSearch | None:
    """Change a saved search; `None` arguments keep their current value. A new query or
    filters make the search due again.

    Returns `None` if there is no such search. Raises `DuplicateSavedSearchError` if
    another search has the resulting query and filters, `ValueError` for a blank or too
    long query or an unknown schedule.
    """
    current = get_saved_search(session, search_id)
    if current is None:
        return None
    new_query = current.query if query is None else normalize_search_query(query)
    new_filters = current.filters if filters is None else filters
    new_schedule = current.schedule if schedule is None else _check_schedule(schedule)
    encoded = encode_filters(new_filters)
    taken = session.execute(
        text(
            "SELECT 1 FROM saved_searches WHERE query = :query AND filters = :filters AND id != :id"
        ),
        {"id": search_id, "query": new_query, "filters": encoded},
    ).first()
    if taken is not None:
        raise DuplicateSavedSearchError(f"The search {new_query!r} is already saved")
    changed_search = new_query != current.query or new_filters != current.filters
    session.execute(
        text(
            """
            UPDATE saved_searches SET
                query = :query,
                filters = :filters,
                schedule = :schedule,
                last_run_at = CASE WHEN :reset THEN NULL ELSE last_run_at END,
                last_found_count = CASE WHEN :reset THEN NULL ELSE last_found_count END,
                last_error = CASE WHEN :reset THEN NULL ELSE last_error END,
                updated_at = :now
            WHERE id = :id
            """
        ),
        {
            "id": search_id,
            "query": new_query,
            "filters": encoded,
            "schedule": new_schedule,
            "reset": changed_search,
            "now": format_timestamp(now or datetime.now(UTC)),
        },
    )
    return get_saved_search(session, search_id)


def delete_saved_search(session: Session, search_id: int) -> bool:
    """Delete a saved search. Returns whether it existed. Candidates it found stay."""
    deleted = session.execute(
        text("DELETE FROM saved_searches WHERE id = :id RETURNING id"), {"id": search_id}
    ).first()
    return deleted is not None


def due_saved_searches(session: Session, *, now: datetime | None = None) -> list[SavedSearch]:
    """The saved searches to run now (see the module docstring), oldest run first."""
    now = now or datetime.now(UTC)
    due = [
        search
        for search in list_saved_searches(session)
        if search.next_run_at is not None
        and (
            search.last_run_at is None
            or _parse_timestamp(search.next_run_at) - SCHEDULE_GRACE <= now
        )
    ]
    return sorted(due, key=lambda search: (search.last_run_at or "", search.id))


def record_run(
    session: Session,
    search_id: int,
    *,
    found_count: int | None = None,
    error: str | None = None,
    now: datetime | None = None,
) -> None:
    """Note that a search ran: successfully, finding `found_count` results, or failing
    with `error` (then the last successful count is kept)."""
    session.execute(
        text(
            """
            UPDATE saved_searches SET
                last_run_at = :now,
                last_found_count = CASE WHEN :error IS NULL THEN :found ELSE last_found_count END,
                last_error = :error
            WHERE id = :id
            """
        ),
        {
            "id": search_id,
            "now": format_timestamp(now or datetime.now(UTC)),
            "found": found_count,
            "error": error,
        },
    )


class SavedSearchSource:
    """Candidates from the saved searches that are due (`due_saved_searches`).

    Each search contributes its top `per_search` results, attributed to it
    (`source_detail` = the query); rated videos are left out. Each run is recorded on
    the search (`record_run`), failed or not. A search that fails is skipped; the
    source fails only if every due search did.
    """

    name = SAVED_SEARCH

    def __init__(
        self,
        sessions: sessionmaker[Session],
        gateway: Gateway,
        *,
        per_search: int = DEFAULT_RESULTS_PER_SEARCH,
        now: datetime | None = None,
    ) -> None:
        self._sessions = sessions
        self._gateway = gateway
        self._per_search = per_search
        self._now = now

    def fetch(self) -> list[FoundVideo]:
        now = self._now or datetime.now(UTC)
        with self._sessions() as session:
            searches = due_saved_searches(session, now=now)
            rated = set(session.execute(text("SELECT video_id FROM ratings")).scalars())
        found: list[FoundVideo] = []
        errors: list[GatewayError] = []
        for search in searches:
            try:
                results = self._gateway.search(search.query, search.filters, limit=self._per_search)
            except GatewayError as error:
                logger.warning("Saved search %r failed: %s", search.query, error)
                errors.append(error)
                with self._sessions.begin() as session:
                    record_run(session, search.id, error=str(error) or error.kind, now=now)
                continue
            with self._sessions.begin() as session:
                record_run(session, search.id, found_count=len(results), now=now)
            found += [
                FoundVideo(
                    video_id=result.id,
                    title=result.title,
                    channel_id=result.channel_id,
                    channel_title=result.channel_title,
                    source_detail=search.query,
                    channel_handle=result.channel_handle,
                    duration_seconds=result.duration_seconds,
                    view_count=result.view_count,
                    thumbnail_url=result.thumbnail_url,
                    live_status=result.live_status,
                )
                for result in results
                if result.id not in rated
            ]
        if errors and len(errors) == len(searches):
            raise errors[-1]
        return found


def _saved_search(row: Sequence[Any]) -> SavedSearch:
    (
        search_id,
        query,
        filters,
        schedule,
        last_run_at,
        last_found_count,
        last_error,
        created_at,
        updated_at,
    ) = row
    schedule = cast(Schedule, schedule)
    next_run_at: str | None = None
    if schedule != "paused":
        next_run_at = (
            created_at
            if last_run_at is None
            else format_timestamp(_parse_timestamp(last_run_at) + SCHEDULE_INTERVALS[schedule])
        )
    return SavedSearch(
        id=search_id,
        query=query,
        filters=decode_filters(filters),
        schedule=schedule,
        next_run_at=next_run_at,
        last_run_at=last_run_at,
        last_found_count=last_found_count,
        last_error=last_error,
        created_at=created_at,
        updated_at=updated_at,
    )


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)
