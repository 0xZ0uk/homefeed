"""The daily feed: building it from the candidate pool and reading stored feeds.

`build_feed` gathers recent candidates, curation and the user's history from the
database, runs the pure ranker and composer, and stores the result as a new feed for
the date. `refresh_feed` polls subscriptions first; the worker runs it daily at
`FEED_REFRESH_TIME` and `POST /feed/refresh` can run it on demand. `get_feed` and
`list_feeds` read feeds back with their items joined to video and channel info.

A date can have several feeds (each refresh adds one, so dismissals and what was shown
stay on record); the feed for a date is the latest one built for it. Dates are local
calendar dates, like `FEED_REFRESH_TIME`.

History sources:
- watched: videos played on the watch page (a `play` watch event) or rated.
- dismissed: feed items with `dismissed_at` set, in any earlier feed.
Subscription candidates from channels no longer subscribed are left out.
"""

import json
import logging
import random
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import poller, watch_events
from homefeed_core.candidates import SUBSCRIPTION, list_candidates
from homefeed_core.composer import ComposeSettings, FeedSlot, compose
from homefeed_core.config import Settings, get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.ranker import (
    ChannelCuration,
    DurationBounds,
    History,
    RankCandidate,
    ScoreBreakdown,
    rank,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeedItem:
    id: int
    position: int  # 0-based
    video_id: str
    title: str
    description: str | None
    duration_seconds: int | None
    published_at: str | None  # ISO 8601 UTC
    thumbnail_url: str | None
    view_count: int | None
    channel_id: str
    channel_title: str
    channel_handle: str | None
    channel_thumbnail_url: str | None
    source: str
    source_detail: str | None
    score: float
    breakdown: ScoreBreakdown
    explanation: str
    is_pinned: bool
    is_exploration: bool
    selection_probability: float | None
    dismissed_at: str | None
    dismiss_reason: str | None


@dataclass(frozen=True)
class FeedSummary:
    id: int
    date: date
    created_at: str  # ISO 8601 UTC
    model_version: str | None
    item_count: int


@dataclass(frozen=True)
class Feed:
    id: int
    date: date
    created_at: str  # ISO 8601 UTC
    model_version: str | None  # None while ranking is rules-only
    items: list[FeedItem]


def local_today(now: datetime | None = None) -> date:
    """Today's date in the process's local time zone."""
    return (now or datetime.now(UTC)).astimezone().date()


def refresh_feed(
    *,
    sessions: sessionmaker[Session] | None = None,
    poll: Callable[[], object] | None = poller.poll_due_channels,
    settings: Settings | None = None,
    rng: random.Random | None = None,
    now: datetime | None = None,
) -> Feed:
    """Poll due subscriptions (unless `poll` is None), then build today's feed.

    A failing poll is logged and the feed is built from the candidates already stored.
    """
    sessions = sessions or get_session_factory()
    if poll is not None:
        try:
            poll()
        except Exception:
            logger.exception("Polling before the feed build failed; using stored candidates")
    with sessions.begin() as session:
        return build_feed(session, settings=settings, rng=rng, now=now)


def build_feed(
    session: Session,
    *,
    feed_date: date | None = None,
    settings: Settings | None = None,
    rng: random.Random | None = None,
    now: datetime | None = None,
) -> Feed:
    """Rank and compose a feed from the candidate pool and store it as the feed for
    `feed_date` (default: today). The caller commits."""
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    feed_date = feed_date or local_today(now)
    curation = load_curation(session)
    pool = load_rank_candidates(session, since=now - timedelta(days=settings.feed_candidate_days))
    # Uploads of channels unsubscribed since they were polled no longer belong.
    pool = [c for c in pool if c.source != SUBSCRIPTION or c.channel_id in curation]
    scored = rank(
        pool,
        curation=curation,
        history=load_history(session),
        bounds=DurationBounds(
            settings.feed_min_duration_seconds, settings.feed_max_duration_seconds
        ),
    )
    slots = compose(
        scored, curation, ComposeSettings(size=settings.feed_size), rng or random.Random()
    )
    feed_id = _store(session, feed_date, slots)
    feed = _get_feed_by_id(session, feed_id)
    assert feed is not None
    logger.info("Built feed for %s: %d items from %d", feed_date, len(slots), len(scored))
    return feed


def get_feed(session: Session, feed_date: date) -> Feed | None:
    """The latest feed built for `feed_date`, or None."""
    feed_id = session.execute(
        text("SELECT id FROM feeds WHERE date = :date ORDER BY created_at DESC, id DESC LIMIT 1"),
        {"date": feed_date.isoformat()},
    ).scalar_one_or_none()
    return None if feed_id is None else _get_feed_by_id(session, feed_id)


def list_feeds(session: Session, *, limit: int = 30) -> list[FeedSummary]:
    """The latest feed of each date, newest date first."""
    rows = session.execute(
        text(
            """
            WITH latest AS (
                SELECT id, date, created_at, model_version,
                       row_number() OVER (
                           PARTITION BY date ORDER BY created_at DESC, id DESC
                       ) AS rank
                FROM feeds
            )
            SELECT l.id, l.date, l.created_at, l.model_version,
                   (SELECT count(*) FROM feed_items AS i WHERE i.feed_id = l.id)
            FROM latest AS l
            WHERE l.rank = 1
            ORDER BY l.date DESC
            LIMIT :limit
            """
        ),
        {"limit": limit},
    )
    return [
        FeedSummary(id, date.fromisoformat(day), created, model, count)
        for id, day, created, model, count in rows
    ]


def load_curation(session: Session) -> dict[str, ChannelCuration]:
    """Channel preferences by channel id, for the ranker and composer."""
    rows = session.execute(text("SELECT channel_id, prior, pinned, muted FROM channel_prefs"))
    return {
        channel_id: ChannelCuration(prior=prior, pinned=bool(pinned), muted=bool(muted))
        for channel_id, prior, pinned, muted in rows
    }


def watched_video_ids(session: Session) -> set[str]:
    """Videos the user has watched: played (a `play` watch event) or rated.

    A rating counts on its own because videos can be rated without being played here
    (e.g. watched elsewhere)."""
    rated = set(session.execute(text("SELECT video_id FROM ratings")).scalars())
    return rated | watch_events.played_video_ids(session)


def dismissed_video_ids(session: Session) -> set[str]:
    """Videos dismissed from any feed."""
    return set(
        session.execute(
            text("SELECT DISTINCT video_id FROM feed_items WHERE dismissed_at IS NOT NULL")
        ).scalars()
    )


def load_history(session: Session) -> History:
    """Watched and dismissed videos and the rating values per channel."""
    rows = session.execute(
        text(
            """
            SELECT v.channel_id, r.value
            FROM ratings AS r JOIN videos AS v ON v.id = r.video_id
            ORDER BY r.rated_at, r.video_id
            """
        )
    )
    channel_ratings: defaultdict[str, list[float]] = defaultdict(list)
    for channel_id, value in rows:
        channel_ratings[channel_id].append(value)
    n_ratings = session.execute(text("SELECT count(*) FROM ratings")).scalar_one()
    return History(
        watched=frozenset(watched_video_ids(session)),
        dismissed=frozenset(dismissed_video_ids(session)),
        channel_ratings=dict(channel_ratings),
        n_ratings=n_ratings,
    )


def load_rank_candidates(session: Session, *, since: datetime | None = None) -> list[RankCandidate]:
    """Candidates first seen at or after `since`, with their video metadata."""
    pool = list_candidates(session, since=since)
    if not pool:
        return []
    videos = {
        row[0]: row
        for row in session.execute(
            text(
                """
                SELECT id, channel_id, title, duration_seconds, live_status, is_short,
                       published_at
                FROM videos WHERE id IN :ids
                """
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": [candidate.video_id for candidate in pool]},
        )
    }
    result: list[RankCandidate] = []
    for candidate in pool:
        _, channel_id, title, duration, live_status, is_short, published_at = videos[
            candidate.video_id
        ]
        result.append(
            RankCandidate(
                video_id=candidate.video_id,
                channel_id=channel_id,
                source=candidate.source,
                source_detail=candidate.source_detail,
                title=title,
                duration_seconds=duration,
                live_status=live_status,
                is_short=bool(is_short),
                published_at=published_at,
                first_seen_at=candidate.first_seen_at,
            )
        )
    return result


def _store(session: Session, feed_date: date, slots: Sequence[FeedSlot]) -> int:
    feed_id = session.execute(
        text("INSERT INTO feeds (date, model_version) VALUES (:date, NULL) RETURNING id"),
        {"date": feed_date.isoformat()},
    ).scalar_one()
    if slots:
        session.execute(
            text(
                """
                INSERT INTO feed_items (feed_id, video_id, position, source, source_detail,
                                        score, breakdown, explanation, is_pinned,
                                        is_exploration, selection_probability)
                VALUES (:feed_id, :video_id, :position, :source, :source_detail,
                        :score, :breakdown, :explanation, :is_pinned,
                        :is_exploration, :selection_probability)
                """
            ),
            [
                {
                    "feed_id": feed_id,
                    "video_id": slot.item.candidate.video_id,
                    "position": slot.position,
                    "source": slot.item.candidate.source,
                    "source_detail": slot.item.candidate.source_detail,
                    "score": slot.item.score,
                    "breakdown": json.dumps(slot.item.breakdown.to_dict()),
                    "explanation": slot.explanation,
                    "is_pinned": int(slot.is_pinned),
                    "is_exploration": int(slot.is_exploration),
                    "selection_probability": slot.selection_probability,
                }
                for slot in slots
            ],
        )
    return feed_id


def _get_feed_by_id(session: Session, feed_id: int) -> Feed | None:
    row = session.execute(
        text("SELECT id, date, created_at, model_version FROM feeds WHERE id = :id"),
        {"id": feed_id},
    ).one_or_none()
    if row is None:
        return None
    items = session.execute(
        text(
            """
            SELECT i.id, i.position, v.id, v.title, v.description, v.duration_seconds,
                   v.published_at, v.thumbnail_url, v.view_count,
                   c.id, c.title, c.handle, c.thumbnail_url,
                   i.source, i.source_detail, i.score, i.breakdown, i.explanation,
                   i.is_pinned, i.is_exploration, i.selection_probability,
                   i.dismissed_at, i.dismiss_reason
            FROM feed_items AS i
            JOIN videos AS v ON v.id = i.video_id
            JOIN channels AS c ON c.id = v.channel_id
            WHERE i.feed_id = :id
            ORDER BY i.position
            """
        ),
        {"id": feed_id},
    )
    return Feed(
        id=row[0],
        date=date.fromisoformat(row[1]),
        created_at=row[2],
        model_version=row[3],
        items=[_item(item) for item in items],
    )


def _item(row: Sequence[Any]) -> FeedItem:
    breakdown = json.loads(row[16])
    return FeedItem(
        *row[:16],
        breakdown=ScoreBreakdown(
            model=breakdown["model"],
            alpha=breakdown["alpha"],
            channel=breakdown["channel"],
            topics=breakdown["topics"],
        ),
        explanation=row[17],
        is_pinned=bool(row[18]),
        is_exploration=bool(row[19]),
        selection_probability=row[20],
        dismissed_at=row[21],
        dismiss_reason=row[22],
    )
