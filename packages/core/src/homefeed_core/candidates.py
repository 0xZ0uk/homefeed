"""The candidate pool: videos that may go into a feed, with where they came from.

Producers call `record` with videos already stored in `videos`. A video is recorded
once per source, keeping the first time that source saw it. Readers such as the daily
feed job call `list_candidates`, which returns each video once, attributed to the
source that found it first.

Subscriptions are recorded by the RSS poller (see homefeed_core.poller), which keeps
its own per-channel schedule. Every other source implements `CandidateSource`, and
`generate` runs them: it stores what each one found and records it, and a source that
fails is logged and skipped without failing the run. Sources:
- `related` (`RelatedVideosSource`): videos YouTube suggests next to the ones rated
  top tier, with the seed video's id as `source_detail` (for "Related to X (A+)").
"""

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import get_session_factory
from homefeed_core.gateway import Gateway, GatewayError, create_gateway
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.grades import GRADES, is_top_tier

logger = logging.getLogger(__name__)

SUBSCRIPTION = "subscription"
# Related videos of a top-tier rated video; source_detail is that video's id (Milestone 2).
RELATED = "related"


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


# Sources


@dataclass(frozen=True)
class FoundVideo:
    """A video a source found, with what the source knows about it.

    Videos not stored yet are stored with these fields (the enricher fetches the rest
    later); stored ones keep their metadata.
    """

    video_id: str
    title: str
    channel_id: str
    channel_title: str
    source_detail: str | None = None  # which one of the source's inputs found it
    channel_handle: str | None = None
    duration_seconds: int | None = None
    view_count: int | None = None
    thumbnail_url: str | None = None
    live_status: str | None = None


class CandidateSource(Protocol):
    """Somewhere candidates come from, besides subscriptions."""

    @property
    def name(self) -> str:
        """Stored as `candidates.source`, e.g. "related"."""
        ...

    def fetch(self) -> list[FoundVideo]:
        """Find videos, most relevant first. Raise if the source failed as a whole."""
        ...


@dataclass(frozen=True)
class GenerateReport:
    new: dict[str, list[str]] = field(default_factory=dict[str, list[str]])  # source -> ids
    failed: dict[str, str] = field(default_factory=dict[str, str])  # source -> error


def generate(
    sources: Sequence[CandidateSource] | None = None,
    *,
    sessions: sessionmaker[Session] | None = None,
    now: datetime | None = None,
) -> GenerateReport:
    """Run each source (by default `default_sources()`) and record what it found.

    A source that raises, or whose results can't be stored, is logged and reported in
    `failed`; the others still run. `new` lists, per source, the ids new to the pool.
    """
    sessions = sessions or get_session_factory()
    sources = default_sources(sessions) if sources is None else sources
    report = GenerateReport()
    for source in sources:
        try:
            found = source.fetch()
            with sessions.begin() as session:
                report.new[source.name] = _record_found(session, source.name, found, now)
        except Exception as error:
            logger.exception("Candidate source %r failed", source.name)
            report.failed[source.name] = str(error) or type(error).__name__
            continue
        logger.info(
            "Candidate source %r found %d videos, %d new",
            source.name,
            len(found),
            len(report.new[source.name]),
        )
    return report


def default_sources(sessions: sessionmaker[Session] | None = None) -> list[CandidateSource]:
    """The production sources run by the daily feed job."""
    sessions = sessions or get_session_factory()
    return [RelatedVideosSource(sessions, create_gateway(sessions))]


def _record_found(
    session: Session, source: str, found: Sequence[FoundVideo], now: datetime | None
) -> list[str]:
    for video in found:
        _store_found(session, video)
    # One `record` per source detail, in order of first appearance, so a video found
    # through several (e.g. related to two seeds) is attributed to the first.
    by_detail: dict[str | None, list[str]] = {}
    for video in found:
        by_detail.setdefault(video.source_detail, []).append(video.video_id)
    new: list[str] = []
    for detail, video_ids in by_detail.items():
        new += record(session, video_ids, source=source, source_detail=detail, now=now)
    return new


def _store_found(session: Session, video: FoundVideo) -> None:
    session.execute(
        text(
            """
            INSERT INTO channels (id, title, handle) VALUES (:id, :title, :handle)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {"id": video.channel_id, "title": video.channel_title, "handle": video.channel_handle},
    )
    session.execute(
        text(
            """
            INSERT INTO videos (id, channel_id, title, duration_seconds, thumbnail_url,
                                live_status, view_count)
            VALUES (:id, :channel_id, :title, :duration_seconds, :thumbnail_url,
                    :live_status, :view_count)
            ON CONFLICT (id) DO NOTHING
            """
        ),
        {
            "id": video.video_id,
            "channel_id": video.channel_id,
            "title": video.title,
            "duration_seconds": video.duration_seconds,
            "thumbnail_url": video.thumbnail_url,
            "live_status": video.live_status,
            "view_count": video.view_count,
        },
    )


# Related videos

DEFAULT_MAX_SEEDS = 20
DEFAULT_RELATED_PER_SEED = 10


class RelatedVideosSource:
    """Videos YouTube suggests next to the ones rated top tier (`grades.is_top_tier`).

    Seeds are the `max_seeds` most recently rated top-tier videos; each contributes up
    to `per_seed` related videos, attributed to it (`source_detail` = the seed's id).
    Rated videos are never candidates of their own. A seed whose related list can't be
    fetched (e.g. a removed video) is skipped; the source fails only if every seed did.
    """

    name = RELATED

    def __init__(
        self,
        sessions: sessionmaker[Session],
        gateway: Gateway,
        *,
        max_seeds: int = DEFAULT_MAX_SEEDS,
        per_seed: int = DEFAULT_RELATED_PER_SEED,
    ) -> None:
        self._sessions = sessions
        self._gateway = gateway
        self._max_seeds = max_seeds
        self._per_seed = per_seed

    def fetch(self) -> list[FoundVideo]:
        with self._sessions() as session:
            seeds = top_tier_video_ids(session, limit=self._max_seeds)
            rated = set(session.execute(text("SELECT video_id FROM ratings")).scalars())
        found: list[FoundVideo] = []
        errors: list[GatewayError] = []
        for seed in seeds:
            try:
                related = self._gateway.get_related(seed, limit=self._per_seed)
            except GatewayError as error:
                logger.warning("Could not fetch videos related to %s: %s", seed, error)
                errors.append(error)
                continue
            found += [
                FoundVideo(
                    video_id=video.id,
                    title=video.title,
                    channel_id=video.channel_id,
                    channel_title=video.channel_title,
                    source_detail=seed,
                    channel_handle=video.channel_handle,
                    duration_seconds=video.duration_seconds,
                    view_count=video.view_count,
                    thumbnail_url=video.thumbnail_url,
                    live_status=video.live_status,
                )
                for video in related
                if video.id not in rated
            ]
        if errors and len(errors) == len(seeds):
            raise errors[-1]
        return found


def top_tier_video_ids(session: Session, *, limit: int | None = None) -> list[str]:
    """Videos rated top tier (A-- and up), most recently rated first."""
    rows = session.execute(
        text(
            """
            SELECT video_id FROM ratings
            WHERE grade IN :grades
            ORDER BY rated_at DESC, video_id
            LIMIT :limit
            """
        ).bindparams(bindparam("grades", expanding=True)),
        {
            "grades": [grade for grade in GRADES if is_top_tier(grade)],
            "limit": -1 if limit is None else limit,
        },
    )
    return list(rows.scalars())
