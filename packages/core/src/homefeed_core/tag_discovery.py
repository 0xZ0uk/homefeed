"""Tag discovery: videos from channels you don't follow, found by searching YouTube for the
tags you subscribed to.

`TagDiscoverySource` is the `candidates.CandidateSource` (named `tag`) that does it. A
subscribed tag is a tag-backed topic (see homefeed_core.curation) whose effective weight
is positive; muted tags (weight at or below zero) are never searched. Each one is
searched for its label once a day (`SEARCH_INTERVAL`, give or take the schedule grace),
and its results become candidates with the tag's slug as `source_detail` (for "Because
you follow #woodworking").

At most `per_tag_per_day` new candidates are recorded per tag per local calendar day,
counted from the candidate pool itself, so the cap holds however often the source runs.
A result is new when its video is not stored yet: videos already in the pool, rated or
watched ones, and videos of subscribed channels are all stored, so none is found again.
Videos of muted channels and videos found by another tag in the same run are left out.

A tag whose search fails is recorded (`last_error`) and tried again at its next turn; the
source fails only if every search that ran did. The daily build and the worker's own job
both run it; a tag already searched today is skipped.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import channel_hides
from homefeed_core.candidates import TAG, FoundVideo
from homefeed_core.curation import list_topics
from homefeed_core.gateway import MAX_SEARCH_LIMIT, Gateway
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.scheduled_search import (
    SearchOutcome,
    error_message,
    is_due,
    raise_if_all_failed,
    run_search,
)

logger = logging.getLogger(__name__)

SEARCH_INTERVAL = timedelta(days=1)
DEFAULT_PER_TAG_PER_DAY = 10
# Results requested per search, as many as there can be: the best matches are mostly known
# after the first days, and the cap applies to what is new.
SEARCH_RESULTS = MAX_SEARCH_LIMIT


@dataclass(frozen=True)
class SubscribedTag:
    id: int
    slug: str
    label: str


def subscribed_tags(session: Session, *, now: datetime | None = None) -> list[SubscribedTag]:
    """The tags with a tag-backed topic of positive effective weight, by label."""
    return [
        SubscribedTag(topic.tag_id, topic.tag_slug, topic.tag_label)
        for topic in list_topics(session, now=now)
        if topic.tag_id is not None
        and topic.tag_slug is not None
        and topic.tag_label is not None
        and topic.effective_weight > 0
    ]


def last_run_at(session: Session, tag_id: int) -> str | None:
    return session.execute(
        text("SELECT last_run_at FROM tag_discovery_runs WHERE tag_id = :id"), {"id": tag_id}
    ).scalar()


def record_run(
    session: Session,
    tag_id: int,
    *,
    found_count: int | None = None,
    error: str | None = None,
    now: datetime | None = None,
) -> None:
    """Note that a tag was searched: successfully, finding `found_count` results, or
    failing with `error` (then the last successful count is kept)."""
    session.execute(
        text(
            """
            INSERT INTO tag_discovery_runs (tag_id, last_run_at, last_found_count, last_error)
            VALUES (:id, :now, :found, :error)
            ON CONFLICT (tag_id) DO UPDATE SET
                last_run_at = excluded.last_run_at,
                last_found_count = CASE WHEN :error IS NULL THEN :found
                                        ELSE last_found_count END,
                last_error = excluded.last_error
            """
        ),
        {
            "id": tag_id,
            "now": format_timestamp(now or datetime.now(UTC)),
            "found": found_count,
            "error": error,
        },
    )


def found_today(session: Session, slug: str, *, now: datetime) -> int:
    """How many candidates the tag has brought in since local midnight."""
    midnight = now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return session.execute(
        text(
            "SELECT count(*) FROM candidates WHERE source = :source AND source_detail = :slug "
            "AND first_seen_at >= :since"
        ),
        {"source": TAG, "slug": slug, "since": format_timestamp(midnight)},
    ).scalar_one()


class TagDiscoverySource:
    """Candidates from searching YouTube for each subscribed tag (see the module
    docstring)."""

    name = TAG

    def __init__(
        self,
        sessions: sessionmaker[Session],
        gateway: Gateway,
        *,
        per_tag_per_day: int = DEFAULT_PER_TAG_PER_DAY,
        now: datetime | None = None,
    ) -> None:
        self._sessions = sessions
        self._gateway = gateway
        self._per_tag_per_day = per_tag_per_day
        self._now = now

    def fetch(self) -> list[FoundVideo]:
        now = self._now or datetime.now(UTC)
        todo: list[tuple[SubscribedTag, int]] = []  # tag, new candidates it may still bring
        with self._sessions() as session:
            for tag in subscribed_tags(session, now=now):
                if not is_due(last_run_at(session, tag.id), SEARCH_INTERVAL, now):
                    continue
                remaining = self._per_tag_per_day - found_today(session, tag.slug, now=now)
                if remaining > 0:
                    todo.append((tag, remaining))
            muted = set(
                session.execute(text("SELECT channel_id FROM channel_prefs WHERE muted")).scalars()
            ) | channel_hides.blocked_channel_ids(session)
            known = set(session.execute(text("SELECT id FROM videos")).scalars())
        found: list[FoundVideo] = []
        outcomes: list[SearchOutcome] = []
        taken: set[str] = set()
        for tag, remaining in todo:
            outcome = run_search(
                self._gateway,
                tag.label,
                limit=SEARCH_RESULTS,
                source_detail=tag.slug,
                skip=known | taken,
            )
            outcomes.append(outcome)
            new = [video for video in outcome.videos if video.channel_id not in muted][:remaining]
            taken.update(video.video_id for video in new)
            found += new
            with self._sessions.begin() as session:
                if outcome.error is not None:
                    record_run(session, tag.id, error=error_message(outcome.error), now=now)
                else:
                    record_run(session, tag.id, found_count=len(new), now=now)
        raise_if_all_failed(outcomes)
        return found
