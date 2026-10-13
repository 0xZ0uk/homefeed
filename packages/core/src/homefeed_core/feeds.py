"""The daily feed: building it from the candidate pool and reading stored feeds.

`build_feed` gathers recent candidates, curation and the user's history from the
database, runs the pure ranker and composer, and stores the result as a new feed for
the date. Ranking uses the active trained model, if one loads (see
homefeed_core.ranking_models), blended in by `alpha`; the feed records its version in
`model_version` (None when ranking was rules-only). `refresh_feed` polls subscriptions
first (and, in the worker, enriches the candidates: see homefeed_core.enricher); the
worker runs it daily at `FEED_REFRESH_TIME` and `POST /feed/refresh` can run it on
demand. `get_feed` and `list_feeds` read feeds back with their items joined to video
and channel info, each marked `watched` if the user has watched it since.
`dismiss_feed_item` hides an item from the user with an optional reason; the video is
then left out of every later feed and counts as a weak negative for training.

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
from collections import Counter, defaultdict
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import curation as curation_prefs
from homefeed_core import poller, watch_events
from homefeed_core.candidates import SUBSCRIPTION, list_candidates
from homefeed_core.composer import (
    ChannelRatings,
    ComposeSettings,
    FeedSlot,
    VideoRef,
    compose,
    referenced_video_ids,
)
from homefeed_core.config import Settings, get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.embeddings import calibration, get_embeddings
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.llm_tags import get_scores
from homefeed_core.ranker import (
    ChannelCuration,
    DurationBounds,
    History,
    KeywordMutes,
    RankCandidate,
    RatedTiers,
    ScoreBreakdown,
    rank,
)
from homefeed_core.ranking_models import load_active_model, ranker_model
from homefeed_core.ratings import list_ratings
from homefeed_core.scores import is_bottom_tier, is_good, is_top_tier
from homefeed_core.tags import get_video_tags

logger = logging.getLogger(__name__)

DISMISS_REASON_MAX_LENGTH = 200


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
    watched: bool  # played or rated, as of when the feed is read (see `watched_video_ids`)


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
    enrich: Callable[[], object] | None = None,
    settings: Settings | None = None,
    rng: random.Random | None = None,
    now: datetime | None = None,
) -> Feed:
    """Poll due subscriptions (unless `poll` is None), enrich candidates (if `enrich` is
    given), then build today's feed.

    A failing poll or enrichment is logged and the feed is built from what is stored.
    """
    sessions = sessions or get_session_factory()
    if poll is not None:
        try:
            poll()
        except Exception:
            logger.exception("Polling before the feed build failed; using stored candidates")
    if enrich is not None:
        try:
            enrich()
        except Exception:
            logger.exception("Enriching before the feed build failed; using stored features")
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
    topics = curation_prefs.topic_vectors(session, now=now)
    active = load_active_model(
        session, data_dir=settings.data_dir, embedding_model=settings.embedding_model
    )
    floors = calibration(settings)
    scored = rank(
        pool,
        curation=curation,
        history=load_history(session),
        bounds=DurationBounds(
            settings.feed_min_duration_seconds, settings.feed_max_duration_seconds
        ),
        keyword_mutes=KeywordMutes(curation_prefs.muted_keywords(session)),
        topics=topics,
        embeddings=get_embeddings(session, [c.video_id for c in pool]),
        rated_tiers=load_rated_tiers(session),
        llm_tags=get_scores(session, [c.video_id for c in pool]),
        video_tags=_tag_confidences(session, topics, [c.video_id for c in pool]),
        model=None if active is None else ranker_model(active.model, now=now),
        similarity_floor=floors.similarity_floor,
        topic_similarity_floor=floors.topic_similarity_floor,
    )
    slots = compose(
        scored,
        curation,
        ComposeSettings(size=settings.feed_size, exploration_slots=settings.feed_exploration_slots),
        rng or random.Random(),
        videos=load_video_refs(session, referenced_video_ids(scored)),
        channel_ratings=load_channel_ratings(session),
    )
    model_version = None if active is None else str(active.version.id)
    feed_id = _store(session, feed_date, slots, model_version=model_version)
    feed = _get_feed_by_id(session, feed_id)
    assert feed is not None
    logger.info(
        "Built feed for %s: %d items from %d, model version %s",
        feed_date,
        len(slots),
        len(scored),
        model_version or "none (rules-only)",
    )
    return feed


def _tag_confidences(
    session: Session, topics: Sequence[curation_prefs.TopicVector], video_ids: Sequence[str]
) -> dict[str, dict[int, float]]:
    """For tag-matched topics: each video's tags as tag id to confidence. Empty (and no
    query) when no topic matches by tag or hides one."""
    if not any(topic.match_mode != "embedding" or topic.hide for topic in topics):
        return {}
    return {
        video_id: {tag.tag_id: tag.confidence for tag in video_tags}
        for video_id, video_tags in get_video_tags(session, video_ids).items()
    }


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


def get_feed_item(session: Session, item_id: int) -> FeedItem | None:
    """A feed item by id, or None."""
    row = session.execute(text(f"{_ITEM_SELECT} WHERE i.id = :id"), {"id": item_id}).one_or_none()
    return None if row is None else _item(row)


def normalize_dismiss_reason(reason: str | None) -> str | None:
    """`reason` with surrounding whitespace removed; None when blank.

    Raises ValueError when the result is longer than `DISMISS_REASON_MAX_LENGTH`."""
    normalized = (reason or "").strip()
    if len(normalized) > DISMISS_REASON_MAX_LENGTH:
        raise ValueError(f"A dismiss reason is at most {DISMISS_REASON_MAX_LENGTH} characters")
    return normalized or None


def dismiss_feed_item(
    session: Session, item_id: int, reason: str | None = None, *, now: datetime | None = None
) -> FeedItem | None:
    """Dismiss a feed item, or return None if there is no such item.

    Sets `dismissed_at` (kept from the first dismissal if dismissed again) and
    `dismiss_reason` (a later reason replaces an earlier one; no reason keeps it). The
    video is left out of every feed built afterwards. Raises ValueError for a reason
    that is too long."""
    reason = normalize_dismiss_reason(reason)
    updated = session.execute(
        text(
            """
            UPDATE feed_items
            SET dismissed_at = coalesce(dismissed_at, :at),
                dismiss_reason = coalesce(:reason, dismiss_reason)
            WHERE id = :id
            RETURNING id
            """
        ),
        {"id": item_id, "at": format_timestamp(now or datetime.now(UTC)), "reason": reason},
    ).first()
    if updated is None:
        return None
    return get_feed_item(session, item_id)


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


def load_channel_ratings(session: Session) -> dict[str, ChannelRatings]:
    """Good (5.5 or higher) and not-good rating counts per channel, for exploration."""
    rows = session.execute(
        text("SELECT v.channel_id, r.score FROM ratings AS r JOIN videos AS v ON v.id = r.video_id")
    )
    good: Counter[str] = Counter()
    not_good: Counter[str] = Counter()
    for channel_id, score in rows:
        (good if is_good(score) else not_good)[channel_id] += 1
    return {
        channel_id: ChannelRatings(good=good[channel_id], not_good=not_good[channel_id])
        for channel_id in good.keys() | not_good.keys()
    }


def load_rated_tiers(session: Session) -> RatedTiers:
    """Embeddings of the top-tier and bottom-tier rated videos (those enriched)."""
    ratings = list_ratings(session)
    embeddings = get_embeddings(session, (rating.video_id for rating in ratings))
    return RatedTiers(
        top={
            r.video_id: embeddings[r.video_id]
            for r in ratings
            if is_top_tier(r.score) and r.video_id in embeddings
        },
        bottom={
            r.video_id: embeddings[r.video_id]
            for r in ratings
            if is_bottom_tier(r.score) and r.video_id in embeddings
        },
    )


def load_video_refs(session: Session, video_ids: Collection[str]) -> dict[str, VideoRef]:
    """Titles and scores (if rated) of stored videos, for explanations."""
    if not video_ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT v.id, v.title, r.score
            FROM videos AS v LEFT JOIN ratings AS r ON r.video_id = v.id
            WHERE v.id IN :ids
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": list(video_ids)},
    )
    return {video_id: VideoRef(title, score) for video_id, title, score in rows}


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
                SELECT id, channel_id, title, description, duration_seconds, live_status,
                       is_short, published_at
                FROM videos WHERE id IN :ids
                """
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": [candidate.video_id for candidate in pool]},
        )
    }
    result: list[RankCandidate] = []
    for candidate in pool:
        _, channel_id, title, description, duration, live_status, is_short, published_at = videos[
            candidate.video_id
        ]
        result.append(
            RankCandidate(
                video_id=candidate.video_id,
                channel_id=channel_id,
                source=candidate.source,
                source_detail=candidate.source_detail,
                title=title,
                description=description,
                duration_seconds=duration,
                live_status=live_status,
                is_short=bool(is_short),
                published_at=published_at,
                first_seen_at=candidate.first_seen_at,
            )
        )
    return result


def _store(
    session: Session, feed_date: date, slots: Sequence[FeedSlot], *, model_version: str | None
) -> int:
    feed_id = session.execute(
        text("INSERT INTO feeds (date, model_version) VALUES (:date, :model) RETURNING id"),
        {"date": feed_date.isoformat(), "model": model_version},
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


_ITEM_SELECT = """
    SELECT i.id, i.position, v.id, v.title, v.description, v.duration_seconds,
           v.published_at, v.thumbnail_url, v.view_count,
           c.id, c.title, c.handle, c.thumbnail_url,
           i.source, i.source_detail, i.score, i.breakdown, i.explanation,
           i.is_pinned, i.is_exploration, i.selection_probability,
           i.dismissed_at, i.dismiss_reason,
           EXISTS (SELECT 1 FROM ratings AS r WHERE r.video_id = v.id)
           OR EXISTS (
               SELECT 1 FROM watch_events AS w
               WHERE w.video_id = v.id AND w.event_type = 'play'
           )
    FROM feed_items AS i
    JOIN videos AS v ON v.id = i.video_id
    JOIN channels AS c ON c.id = v.channel_id
"""


def _get_feed_by_id(session: Session, feed_id: int) -> Feed | None:
    row = session.execute(
        text("SELECT id, date, created_at, model_version FROM feeds WHERE id = :id"),
        {"id": feed_id},
    ).one_or_none()
    if row is None:
        return None
    items = session.execute(
        text(f"{_ITEM_SELECT} WHERE i.feed_id = :id ORDER BY i.position"), {"id": feed_id}
    )
    return Feed(
        id=row[0],
        date=date.fromisoformat(row[1]),
        created_at=row[2],
        model_version=row[3],
        items=[_item(item) for item in items],
    )


def _item(row: Sequence[Any]) -> FeedItem:
    return FeedItem(
        *row[:16],
        breakdown=ScoreBreakdown.from_dict(json.loads(row[16])),
        explanation=row[17],
        is_pinned=bool(row[18]),
        is_exploration=bool(row[19]),
        selection_probability=row[20],
        dismissed_at=row[21],
        dismiss_reason=row[22],
        watched=bool(row[23]),
    )
