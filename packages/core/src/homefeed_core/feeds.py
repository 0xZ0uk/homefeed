"""The daily feed: building it from the candidate pool and reading stored feeds.

`build_feed` gathers recent candidates, curation and the user's history from the
database, runs the pure ranker and composer, and stores the result as a new feed for
the date. Ranking uses the active trained model, if one loads (see
homefeed_core.ranking_models), blended in by `alpha`; the feed records its version in
`model_version` (None when ranking was rules-only). `refresh_feed` polls subscriptions
first (and, in the worker, enriches the candidates: see homefeed_core.enricher); the
worker runs it daily at `FEED_REFRESH_TIME` and `POST /feed/refresh` can run it on
demand. `get_feed` and `list_feeds` read feeds back with their items joined to video
and channel info, each marked `watched` if the user has watched it since. An item also
carries what its card shows to help decide: whether its channel is subscribed, the
video's rating, feedback ("more like this" or "less like this", see homefeed_core.feedback)
and progress through it, up to three tags and its LLM scores.
`extend_feed` appends the next page of ranked picks to a stored feed (the "Show more"
button), leaving out videos already in it. `dismiss_feed_item` hides an item from the
user with an optional reason; the video is then left out of every later feed and counts
as a weak negative for training. `undismiss_feed_item` takes that back. `discover` ranks
the pool the same way for the home page's Discovery carousel: the best picks from outside
the subscriptions, not stored. `wildcards` picks from the same pool a few videos on topics
the user doesn't follow, for the closing block of the home page, also not stored.

A date can have several feeds (each refresh adds one, so dismissals and what was shown
stay on record); the feed for a date is the latest one built for it. Dates are local
calendar dates, like `FEED_REFRESH_TIME`, in the user's time zone (see `local_today`).

The feed size, exploration slots, the most of a feed one topic may take (`feed_max_topic_share`,
see homefeed_core.composer) and duration bounds are user settings (see
homefeed_core.user_settings): stored values over `settings`.

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
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta, tzinfo
from typing import Any

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import channel_hides, poller, watch_events
from homefeed_core import curation as curation_prefs
from homefeed_core.candidates import SUBSCRIPTION, TAG, list_candidates
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
from homefeed_core.feedback import LESS, MORE, list_feedback
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.history import watched_fractions
from homefeed_core.llm_tags import LLMTags, get_scores
from homefeed_core.ranker import (
    ChannelCuration,
    DurationBounds,
    History,
    KeywordMutes,
    RankCandidate,
    RatedTiers,
    ScoreBreakdown,
    ScoredCandidate,
    rank,
)
from homefeed_core.ranking_models import load_active_model, ranker_model
from homefeed_core.ratings import list_ratings
from homefeed_core.scores import is_bottom_tier, is_good, is_top_tier
from homefeed_core.tags import VideoTag, get_video_tags
from homefeed_core.user_settings import get_user_settings

logger = logging.getLogger(__name__)

DISMISS_REASON_MAX_LENGTH = 200
# Tags a feed or Discovery item carries for its card, the most confident first.
ITEM_TAGS = 3


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
    # The rest is as of when the feed is read, too.
    rating: int | None  # the video's score, 1 to 10
    watched_fraction: float | None  # how far through it the user got, 0 to 1
    feedback: int | None  # 1: more like this, -1: less like this
    channel_subscribed: bool  # whether the channel has preferences, as a subscription does
    tags: tuple[VideoTag, ...]  # up to `ITEM_TAGS`, the most confident first
    llm: LLMTags | None  # None until the video is LLM-tagged


@dataclass(frozen=True)
class DiscoveryItem:
    video_id: str
    title: str
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
    channel_subscribed: bool
    feedback: int | None  # 1: more like this, -1: less like this
    tags: tuple[VideoTag, ...]  # up to `ITEM_TAGS`, the most confident first
    llm: LLMTags | None  # None until the video is LLM-tagged


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


def local_today(now: datetime | None = None, tz: tzinfo | None = None) -> date:
    """Today's date in `tz`, the user's time zone (`UserSettings.tz`); None is the
    process's local time zone."""
    return (now or datetime.now(UTC)).astimezone(tz).date()


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
    feed_date = feed_date or local_today(now, get_user_settings(session, settings).tz)
    slots, scored_count, model_version = _rank_and_compose(
        session, settings=settings, rng=rng, now=now, exclude=()
    )
    feed_id = _create_feed(session, feed_date, model_version=model_version)
    _store_items(session, feed_id, slots, offset=0)
    feed = _get_feed_by_id(session, feed_id)
    assert feed is not None
    logger.info(
        "Built feed for %s: %d items from %d, model version %s",
        feed_date,
        len(slots),
        scored_count,
        model_version or "none (rules-only)",
    )
    return feed


def extend_feed(
    session: Session,
    feed_id: int,
    *,
    settings: Settings | None = None,
    rng: random.Random | None = None,
    now: datetime | None = None,
) -> Feed | None:
    """Append the next `feed_size` ranked picks to a feed and return it, or None if
    there is no such feed.

    Videos already in the feed (dismissed ones included) are left out. When nothing new
    is left the feed is returned unchanged. Only what the user asked to see is stored,
    since insights count stored items as shown. The caller commits."""
    feed = _get_feed_by_id(session, feed_id)
    if feed is None:
        return None
    settings = settings or get_settings()
    slots, _, _ = _rank_and_compose(
        session,
        settings=settings,
        rng=rng,
        now=now or datetime.now(UTC),
        exclude={item.video_id for item in feed.items},
    )
    if not slots:
        return feed
    _store_items(session, feed_id, slots, offset=len(feed.items))
    extended = _get_feed_by_id(session, feed_id)
    assert extended is not None
    logger.info("Extended feed %d with %d items", feed_id, len(slots))
    return extended


# Videos in the home page's Discovery carousel.
DISCOVERY_SIZE = 10


def discover(
    session: Session,
    *,
    size: int = DISCOVERY_SIZE,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> list[DiscoveryItem]:
    """Up to `size` of the best-ranked candidates from outside the subscriptions (found
    by related videos, featured channels, tag searches, saved searches and external
    sources), one per channel, best first.

    Ranking is the feed's, so watched, dismissed and filtered videos never show, and
    no topic takes more than its share (`feed_max_topic_share`). Videos of subscribed
    channels and every video in today's feed (dismissed ones included) are left out too,
    so the carousel doesn't repeat the feed. Nothing is stored and there's no
    randomness: the picks change only when the pool or the ranking does."""
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    user = get_user_settings(session, settings)
    in_todays_feed = _feed_video_ids(session, local_today(now, user.tz))
    subscribed = set(curation_prefs.subscribed_channel_ids(session))
    ranking = _rank_pool(
        session,
        settings=settings,
        now=now,
        exclude=in_todays_feed,
        keep=lambda c: c.source != SUBSCRIPTION and c.channel_id not in subscribed,
    )
    slots = _compose(
        session,
        ranking,
        ComposeSettings(
            size=size,
            per_channel_cap=1,
            exploration_slots=0,
            max_topic_share=user.feed_max_topic_share,
        ),
        random.Random(0),  # ties only; no exploration
    )
    return _discovery_items(session, slots)


def _discovery_items(session: Session, slots: Sequence[FeedSlot]) -> list[DiscoveryItem]:
    if not slots:
        return []
    video_ids = [slot.item.candidate.video_id for slot in slots]
    rows = {
        row[0]: row
        for row in session.execute(
            text(
                """
                SELECT v.id, v.title, v.duration_seconds, v.published_at, v.thumbnail_url,
                       v.view_count, c.id, c.title, c.handle, c.thumbnail_url,
                       EXISTS (SELECT 1 FROM channel_prefs AS p WHERE p.channel_id = c.id),
                       (SELECT f.signal FROM video_feedback AS f WHERE f.video_id = v.id)
                FROM videos AS v JOIN channels AS c ON c.id = v.channel_id
                WHERE v.id IN :ids
                """
            ).bindparams(bindparam("ids", expanding=True)),
            {"ids": video_ids},
        )
    }
    tags = get_video_tags(session, video_ids)
    llm = get_scores(session, video_ids)
    items: list[DiscoveryItem] = []
    for slot in slots:
        video_id = slot.item.candidate.video_id
        if video_id not in rows:
            continue
        row = rows[video_id]
        items.append(
            DiscoveryItem(
                *row[:10],
                source=slot.item.candidate.source,
                source_detail=slot.item.candidate.source_detail,
                score=slot.item.score,
                breakdown=slot.item.breakdown,
                explanation=slot.explanation,
                channel_subscribed=bool(row[10]),
                feedback=row[11],
                tags=tuple(tags.get(video_id, ())[:ITEM_TAGS]),
                llm=llm.get(video_id),
            )
        )
    return items


# Videos in the closing block of the home page, "Show 3 wildcards".
WILDCARD_SIZE = 3
# The wildcards are drawn from this many of the best candidates.
WILDCARD_POOL = 20
# How many days back they look for candidates: further than the feed does, since the
# closing block comes once "Show more" has shown everything in the feed's own window.
WILDCARD_DAYS = 30
WILDCARD_EXPLANATION = "Wildcard: outside the topics you follow"


def wildcards(
    session: Session,
    *,
    size: int = WILDCARD_SIZE,
    exclude: Collection[str] = (),
    settings: Settings | None = None,
    now: datetime | None = None,
) -> list[DiscoveryItem]:
    """Up to `size` videos from outside everything the feed is built around, for the end
    of the day's feed: a nudge to look past the usual.

    A candidate qualifies when it passes the feed's filters (so it is not watched or
    dismissed, a short, live, outside the duration bounds or muted by a keyword), is
    not in today's feed or among the `exclude`d videos (what else the page shows), comes
    from a channel that is neither subscribed nor hidden, and shares no tag with the tags
    I follow or mute (tag searches, which exist to find a followed tag's videos, don't
    count as candidates at all). They look back `WILDCARD_DAYS` days, further than the
    feed does: once "Show more" has nothing more, every candidate of the feed's window is
    in the feed, and the wildcards are what lies beyond it. The qualifying channels' best
    videos, one per channel, are ranked: those with tags and an embedding first, since
    only they are known to be outside my topics and to suit my taste, then by similarity
    to the videos I rated well, then newest first. The picks are a random draw from the
    best `WILDCARD_POOL`, seeded with the date so they stay the same all day for as long
    as the pool does, and come back best first. Nothing is stored."""
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    user = get_user_settings(session, settings)
    today = local_today(now, user.tz)
    subscribed = set(curation_prefs.subscribed_channel_ids(session))
    hidden = {hide.channel_id for hide in channel_hides.list_hides(session)}
    ranking = _rank_pool(
        session,
        settings=settings,
        now=now,
        exclude=_feed_video_ids(session, today) | set(exclude),
        candidate_days=WILDCARD_DAYS,
        keep=lambda c: (
            c.source not in (SUBSCRIPTION, TAG)
            and c.channel_id not in subscribed
            and c.channel_id not in hidden
        ),
    )
    video_tags = get_video_tags(session, [item.candidate.video_id for item in ranking.scored])
    weighted = {s.tag_id for s in curation_prefs.list_tag_subscriptions(session) if s.weight != 0}
    outside = [
        item
        for item in ranking.scored
        if not any(tag.tag_id in weighted for tag in video_tags.get(item.candidate.video_id, ()))
    ]

    def known(item: ScoredCandidate) -> int:
        """How much is known of the video: whether it has tags, and an embedding."""
        return (item.candidate.video_id in video_tags) + (
            item.breakdown.similarity_features is not None
        )

    # Each sort keeps the order of the one before it for ties: newest, then similar, then known.
    outside.sort(key=lambda item: item.candidate.published_at or "", reverse=True)
    outside.sort(key=lambda item: item.breakdown.similarity, reverse=True)
    outside.sort(key=known, reverse=True)
    best: list[ScoredCandidate] = []
    channels: set[str] = set()
    for item in outside:
        if item.candidate.channel_id not in channels and len(best) < WILDCARD_POOL:
            channels.add(item.candidate.channel_id)
            best.append(item)
    drawn = random.Random(f"wildcards:{today.isoformat()}").sample(
        range(len(best)), k=min(size, len(best))
    )
    slots = [
        FeedSlot(item=best[index], position=position, explanation=WILDCARD_EXPLANATION)
        for position, index in enumerate(sorted(drawn))
    ]
    return _discovery_items(session, slots)


def _rank_and_compose(
    session: Session,
    *,
    settings: Settings,
    rng: random.Random | None,
    now: datetime,
    exclude: Collection[str],
) -> tuple[list[FeedSlot], int, str | None]:
    """Rank the candidate pool, drop `exclude`d videos and compose one page of
    `feed_size` slots. Returns the slots, how many candidates were left after ranking
    and the active model version (None when rules-only)."""
    user = get_user_settings(session, settings)
    ranking = _rank_pool(session, settings=settings, now=now, exclude=exclude)
    slots = _compose(
        session,
        ranking,
        ComposeSettings(
            size=user.feed_size,
            exploration_slots=user.feed_exploration_slots,
            max_topic_share=user.feed_max_topic_share,
        ),
        rng or random.Random(),
    )
    return slots, len(ranking.scored), ranking.model_version


@dataclass(frozen=True)
class _Ranking:
    scored: list[ScoredCandidate]
    curation: dict[str, ChannelCuration]
    model_version: str | None  # None when rules-only


def _rank_pool(
    session: Session,
    *,
    settings: Settings,
    now: datetime,
    exclude: Collection[str],
    keep: Callable[[RankCandidate], bool] | None = None,
    candidate_days: int | None = None,
) -> _Ranking:
    """Rank the recent candidate pool (only the candidates `keep` accepts, if given),
    best first, leaving out `exclude`d videos. The pool is what entered it in the last
    `feed_candidate_days` days, or `candidate_days` if given."""
    user = get_user_settings(session, settings)
    curation = load_curation(session, now=now)
    days = settings.feed_candidate_days if candidate_days is None else candidate_days
    pool = load_rank_candidates(session, since=now - timedelta(days=days))
    # Uploads of channels unsubscribed since they were polled no longer belong.
    pool = [c for c in pool if c.source != SUBSCRIPTION or c.channel_id in curation]
    if keep is not None:
        pool = [c for c in pool if keep(c)]
    tag_subscriptions = curation_prefs.list_tag_subscriptions(session)
    active = load_active_model(
        session, data_dir=settings.data_dir, embedding_model=settings.embedding_model
    )
    floors = calibration(settings)
    scored = rank(
        pool,
        curation=curation,
        history=load_history(session),
        bounds=DurationBounds(user.feed_min_duration_seconds, user.feed_max_duration_seconds),
        keyword_mutes=KeywordMutes(curation_prefs.muted_keywords(session)),
        tags=tag_subscriptions,
        embeddings=get_embeddings(session, [c.video_id for c in pool]),
        rated_tiers=load_rated_tiers(session),
        llm_tags=get_scores(session, [c.video_id for c in pool]),
        video_tags=_tag_confidences(session, tag_subscriptions, [c.video_id for c in pool]),
        model=None if active is None else ranker_model(active.model, now=now),
        similarity_floor=floors.similarity_floor,
    )
    if exclude:
        scored = [item for item in scored if item.candidate.video_id not in exclude]
    return _Ranking(scored, curation, None if active is None else str(active.version.id))


def _compose(
    session: Session, ranking: _Ranking, settings: ComposeSettings, rng: random.Random
) -> list[FeedSlot]:
    return list(
        compose(
            ranking.scored,
            ranking.curation,
            settings,
            rng,
            videos=load_video_refs(session, referenced_video_ids(ranking.scored)),
            channel_ratings=load_channel_ratings(session),
        )
    )


def _tag_confidences(
    session: Session,
    tag_subscriptions: Sequence[curation_prefs.TagSubscription],
    video_ids: Sequence[str],
) -> dict[str, dict[int, float]]:
    """For the subscribed and muted tags: each video's tags as tag id to confidence. Empty
    (and no query) without any."""
    if not tag_subscriptions:
        return {}
    return {
        video_id: {tag.tag_id: tag.confidence for tag in video_tags}
        for video_id, video_tags in get_video_tags(session, video_ids).items()
    }


def _feed_video_ids(session: Session, feed_date: date) -> set[str]:
    """The videos in the latest feed built for `feed_date`, dismissed ones included. It
    reads no more than that, unlike `get_feed`."""
    return set(
        session.execute(
            text(
                """
                SELECT i.video_id FROM feed_items AS i
                WHERE i.feed_id = (
                    SELECT id FROM feeds WHERE date = :date
                    ORDER BY created_at DESC, id DESC LIMIT 1
                )
                """
            ),
            {"date": feed_date.isoformat()},
        ).scalars()
    )


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
    return None if row is None else _items(session, [row])[0]


def undismiss_feed_item(session: Session, item_id: int) -> FeedItem | None:
    """Take a dismissal back, or return None if there is no such item.

    Clears `dismissed_at` and `dismiss_reason`, so the item is as it was before it was
    dismissed, and returns it. An item that isn't dismissed is returned unchanged. The
    video is no longer left out of later feeds because of this item (it still is if
    another item of the same video, in an earlier feed, was dismissed)."""
    updated = session.execute(
        text(
            """
            UPDATE feed_items SET dismissed_at = NULL, dismiss_reason = NULL
            WHERE id = :id
            RETURNING id
            """
        ),
        {"id": item_id},
    ).first()
    if updated is None:
        return None
    return get_feed_item(session, item_id)


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


def load_curation(session: Session, *, now: datetime | None = None) -> dict[str, ChannelCuration]:
    """Channel preferences by channel id, for the ranker and composer. A channel counts as
    muted while it is muted for good or until a time still ahead of `now` (default: the
    current time), and so does a blocked one (see `channel_hides`), keeping its other
    preferences if subscribed."""
    rows = session.execute(
        text(
            f"""
            SELECT p.channel_id, p.prior, p.pinned, {curation_prefs.muted_sql("p")}
            FROM channel_prefs AS p
            """
        ),
        {"now": format_timestamp(now or datetime.now(UTC))},
    )
    result = {
        channel_id: ChannelCuration(prior=prior, pinned=bool(pinned), muted=bool(muted))
        for channel_id, prior, pinned, muted in rows
    }
    for channel_id in channel_hides.blocked_channel_ids(session):
        result[channel_id] = replace(result.get(channel_id, ChannelCuration()), muted=True)
    return result


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
    """Good (6 or higher) and not-good rating counts per channel, for exploration."""
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
    """Embeddings of the top-tier and bottom-tier videos (those enriched): rated 7 and up
    or 4 and down, and unrated videos marked "more like this" (top tier) or "less like
    this" (bottom tier). An explicit rating always wins over feedback: a rated video
    counts by its score alone, so one rated 5 or 6 is in neither tier whatever its
    feedback."""
    ratings = list_ratings(session)
    rated = {rating.video_id for rating in ratings}
    marked = [item for item in list_feedback(session) if item.video_id not in rated]
    top = [r.video_id for r in ratings if is_top_tier(r.score)]
    top += [f.video_id for f in marked if f.signal == MORE]
    bottom = [r.video_id for r in ratings if is_bottom_tier(r.score)]
    bottom += [f.video_id for f in marked if f.signal == LESS]
    embeddings = get_embeddings(session, [*top, *bottom])
    return RatedTiers(
        top={video_id: embeddings[video_id] for video_id in top if video_id in embeddings},
        bottom={video_id: embeddings[video_id] for video_id in bottom if video_id in embeddings},
    )


def load_video_refs(session: Session, video_ids: Collection[str]) -> dict[str, VideoRef]:
    """Titles, scores (if rated) and feedback of stored videos, for explanations."""
    if not video_ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT v.id, v.title, r.score, f.signal
            FROM videos AS v
            LEFT JOIN ratings AS r ON r.video_id = v.id
            LEFT JOIN video_feedback AS f ON f.video_id = v.id
            WHERE v.id IN :ids
            """
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": list(video_ids)},
    )
    return {video_id: VideoRef(title, score, signal) for video_id, title, score, signal in rows}


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


def _create_feed(session: Session, feed_date: date, *, model_version: str | None) -> int:
    return session.execute(
        text("INSERT INTO feeds (date, model_version) VALUES (:date, :model) RETURNING id"),
        {"date": feed_date.isoformat(), "model": model_version},
    ).scalar_one()


def _store_items(session: Session, feed_id: int, slots: Sequence[FeedSlot], *, offset: int) -> None:
    """Insert `slots` into a feed, their positions shifted by `offset` (the number of
    items already there) so positions stay contiguous."""
    if not slots:
        return
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
                "position": offset + slot.position,
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


_ITEM_SELECT = """
    SELECT i.id, i.position, v.id, v.title, v.description, v.duration_seconds,
           v.published_at, v.thumbnail_url, v.view_count,
           c.id, c.title, c.handle, c.thumbnail_url,
           i.source, i.source_detail, i.score, i.breakdown, i.explanation,
           i.is_pinned, i.is_exploration, i.selection_probability,
           i.dismissed_at, i.dismiss_reason,
           r.video_id IS NOT NULL OR EXISTS (
               SELECT 1 FROM watch_events AS w
               WHERE w.video_id = v.id AND w.event_type = 'play'
           ),
           r.score, f.signal,
           EXISTS (SELECT 1 FROM channel_prefs AS p WHERE p.channel_id = c.id)
    FROM feed_items AS i
    JOIN videos AS v ON v.id = i.video_id
    JOIN channels AS c ON c.id = v.channel_id
    LEFT JOIN ratings AS r ON r.video_id = v.id
    LEFT JOIN video_feedback AS f ON f.video_id = v.id
"""


def _get_feed_by_id(session: Session, feed_id: int) -> Feed | None:
    row = session.execute(
        text("SELECT id, date, created_at, model_version FROM feeds WHERE id = :id"),
        {"id": feed_id},
    ).one_or_none()
    if row is None:
        return None
    rows = session.execute(
        text(f"{_ITEM_SELECT} WHERE i.feed_id = :id ORDER BY i.position"), {"id": feed_id}
    ).all()
    return Feed(
        id=row[0],
        date=date.fromisoformat(row[1]),
        created_at=row[2],
        model_version=row[3],
        items=_items(session, rows),
    )


def _items(session: Session, rows: Sequence[Sequence[Any]]) -> list[FeedItem]:
    """Feed items from `_ITEM_SELECT` rows, with the details that take a query of their own
    (tags and LLM scores for all items at once, progress for those that are `watched`)."""
    video_ids = [row[2] for row in rows]
    tags = get_video_tags(session, video_ids)
    llm = get_scores(session, video_ids)
    progress = watched_fractions(session, [row[2] for row in rows if row[23]])
    return [
        FeedItem(
            *row[:16],
            breakdown=ScoreBreakdown.from_dict(json.loads(row[16])),
            explanation=row[17],
            is_pinned=bool(row[18]),
            is_exploration=bool(row[19]),
            selection_probability=row[20],
            dismissed_at=row[21],
            dismiss_reason=row[22],
            watched=bool(row[23]),
            rating=row[24],
            watched_fraction=progress.get(row[2]),
            feedback=row[25],
            channel_subscribed=bool(row[26]),
            tags=tuple(tags.get(row[2], ())[:ITEM_TAGS]),
            llm=llm.get(row[2]),
        )
        for row in rows
    ]
