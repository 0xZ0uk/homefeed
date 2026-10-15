"""What the app has learned about the user: the facts behind the Taste page.

`taste_summary` gathers what steers the feed and leaves what to make of it (a topic that
takes most of the picks, a followed one that hardly shows up) to the page:

- Topics: every followed or muted tag (`tag_subscriptions`) with its weight and, over the
  last `days` days, its picks: the distinct videos carrying it that were in a feed built
  in the window, and how many of those were watched (played or rated, at any time). A
  video counts once however many feeds held it (a refresh builds another), as in
  `channel_health`, and a removed tag link (a tombstone) is no link. `total_picks` is
  every distinct video picked in the window, what a topic's share of the picks is a share
  of. A video usually has several tags, so the shares of different topics overlap. Ratings
  of videos carrying the tag are counted over all time, as `channel_health` does for
  channels: there are few of them, and they are the evidence the app has about a topic.
- Channels: how many subscribed channels hold each preference, and the channels the user
  does not follow but rated well: an average of `WELL_RATED_AVERAGE` or more from at least
  `WELL_RATED_MIN_RATINGS` ratings, the best `WELL_RATED_LIMIT` of them. A channel hidden
  from Discover is left out, since that was a decision. Only videos stored in `videos`
  belong to a channel, so only those count.
- Signals: how the app learns from the user. How many videos are rated, and how many have
  been watched (played or rated, like the feed's own `watched` mark), "More like this" and
  "Less like this" (see homefeed_core.feedback), and the videos dismissed from a feed in
  the window by reason; a dismissal without a reason is a group of its own.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core.channel_health import PICKS_WINDOW_DAYS
from homefeed_core.curation import PRIORS, Prior
from homefeed_core.feedback import LESS, MORE
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.scores import TOP_TIER_THRESHOLD

# How far back picks and dismissals are counted, in days: the window of a channel's picks.
DEFAULT_DAYS = PICKS_WINDOW_DAYS
MAX_DAYS = 365

# A channel is rated well when its videos average this (the liked set starts here) ...
WELL_RATED_AVERAGE = TOP_TIER_THRESHOLD
# ... from at least this many ratings, so a single lucky video doesn't make a favourite.
WELL_RATED_MIN_RATINGS = 2
# At most this many such channels are listed, the best first.
WELL_RATED_LIMIT = 10


@dataclass(frozen=True)
class TagTaste:
    """A followed or muted tag and how it fares in the feed."""

    tag_id: int
    slug: str
    label: str
    weight: float  # the slider, in [-1, 1]: positive followed, negative muted
    hide: bool  # a muted tag at -1 can drop its videos from the feed
    picks: int  # distinct videos with the tag in feeds built in the window
    watched_picks: int  # of those, the ones played or rated (at any time)
    rating_count: int  # videos with the tag that are rated, all time
    average_score: float | None  # their average score, 1 to 10; None without ratings


@dataclass(frozen=True)
class PriorCounts:
    """How many subscribed channels hold each preference."""

    love: int
    like: int
    neutral: int
    skeptical: int


@dataclass(frozen=True)
class RatedChannel:
    """A channel that is not followed, whose videos were rated well."""

    channel_id: str
    title: str
    handle: str | None
    thumbnail_url: str | None
    rating_count: int
    average_score: float


@dataclass(frozen=True)
class DismissalCount:
    reason: str | None  # None: dismissed without a reason
    count: int  # distinct videos


@dataclass(frozen=True)
class Signals:
    ratings: int  # videos rated, all time
    watched: int  # videos played or rated, all time; the ratings are among them
    more_like_this: int  # videos marked "more like this"
    less_like_this: int  # videos marked "less like this"
    dismissals: list[DismissalCount]  # in the window; the most common reason first


@dataclass(frozen=True)
class Taste:
    days: int  # the window picks and dismissals are counted over
    total_picks: int  # distinct videos in feeds built in the window
    tags: list[TagTaste]  # followed and muted, by label
    channel_priors: PriorCounts
    unfollowed_channels: list[RatedChannel]  # rated well, best first
    signals: Signals


def taste_summary(
    session: Session, *, days: int = DEFAULT_DAYS, now: datetime | None = None
) -> Taste:
    """The taste facts, with picks and dismissals counted over the last `days` days up to
    `now` (default: the current time). Raises ValueError for `days` outside 1 to
    `MAX_DAYS`."""
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_DAYS}")
    since = format_timestamp((now or datetime.now(UTC)) - timedelta(days=days))
    return Taste(
        days=days,
        total_picks=_total_picks(session, since),
        tags=_tags(session, since),
        channel_priors=_channel_priors(session),
        unfollowed_channels=_unfollowed_channels(session),
        signals=_signals(session, since),
    )


def _total_picks(session: Session, since: str) -> int:
    return session.execute(
        text(
            """
            SELECT count(DISTINCT i.video_id)
            FROM feed_items AS i JOIN feeds AS f ON f.id = i.feed_id
            WHERE f.created_at >= :since
            """
        ),
        {"since": since},
    ).scalar_one()


def _tags(session: Session, since: str) -> list[TagTaste]:
    subscriptions = session.execute(
        text(
            """
            SELECT s.tag_id, t.slug, t.label, s.weight, s.hide
            FROM tag_subscriptions AS s JOIN tags AS t ON t.id = s.tag_id
            ORDER BY t.label COLLATE NOCASE, t.id
            """
        )
    ).all()
    picked = {
        tag_id: (picks, watched)
        for tag_id, picks, watched in session.execute(
            text(
                """
                WITH picked AS (
                    SELECT DISTINCT i.video_id
                    FROM feed_items AS i JOIN feeds AS f ON f.id = i.feed_id
                    WHERE f.created_at >= :since
                )
                SELECT vt.tag_id, count(*),
                       coalesce(sum(
                           EXISTS (SELECT 1 FROM ratings AS r WHERE r.video_id = p.video_id)
                           OR EXISTS (
                               SELECT 1 FROM watch_events AS e
                               WHERE e.video_id = p.video_id AND e.event_type = 'play'
                           )
                       ), 0)
                FROM picked AS p
                JOIN video_tags AS vt ON vt.video_id = p.video_id AND vt.removed_at IS NULL
                JOIN tag_subscriptions AS s ON s.tag_id = vt.tag_id
                GROUP BY vt.tag_id
                """
            ),
            {"since": since},
        )
    }
    rated = {
        tag_id: (count, average)
        for tag_id, count, average in session.execute(
            text(
                """
                SELECT vt.tag_id, count(*), avg(r.score)
                FROM ratings AS r
                JOIN video_tags AS vt ON vt.video_id = r.video_id AND vt.removed_at IS NULL
                JOIN tag_subscriptions AS s ON s.tag_id = vt.tag_id
                GROUP BY vt.tag_id
                """
            )
        )
    }
    result = []
    for tag_id, slug, label, weight, hide in subscriptions:
        picks, watched = picked.get(tag_id, (0, 0))
        count, average = rated.get(tag_id, (0, None))
        result.append(
            TagTaste(
                tag_id=tag_id,
                slug=slug,
                label=label,
                weight=weight,
                hide=bool(hide),
                picks=picks,
                watched_picks=watched,
                rating_count=count,
                average_score=None if average is None else float(average),
            )
        )
    return result


def _channel_priors(session: Session) -> PriorCounts:
    counts: dict[Prior, int] = dict.fromkeys(PRIORS, 0)
    for prior, count in session.execute(
        text("SELECT prior, count(*) FROM channel_prefs GROUP BY prior")
    ):
        counts[prior] = count
    return PriorCounts(**counts)


def _unfollowed_channels(session: Session) -> list[RatedChannel]:
    rows = session.execute(
        text(
            """
            SELECT c.id, c.title, c.handle, c.thumbnail_url, count(*), avg(r.score)
            FROM ratings AS r
            JOIN videos AS v ON v.id = r.video_id
            JOIN channels AS c ON c.id = v.channel_id
            WHERE NOT EXISTS (SELECT 1 FROM channel_prefs AS p WHERE p.channel_id = c.id)
              AND NOT EXISTS (SELECT 1 FROM channel_hides AS h WHERE h.channel_id = c.id)
            GROUP BY c.id
            HAVING count(*) >= :min_ratings AND avg(r.score) >= :min_average
            ORDER BY avg(r.score) DESC, count(*) DESC, c.title COLLATE NOCASE, c.id
            LIMIT :limit
            """
        ),
        {
            "min_ratings": WELL_RATED_MIN_RATINGS,
            "min_average": WELL_RATED_AVERAGE,
            "limit": WELL_RATED_LIMIT,
        },
    )
    return [
        RatedChannel(
            channel_id=channel_id,
            title=title,
            handle=handle,
            thumbnail_url=thumbnail_url,
            rating_count=count,
            average_score=float(average),
        )
        for channel_id, title, handle, thumbnail_url, count, average in rows
    ]


def _signals(session: Session, since: str) -> Signals:
    ratings = session.execute(text("SELECT count(*) FROM ratings")).scalar_one()
    watched = session.execute(
        text(
            """
            SELECT count(*) FROM (
                SELECT video_id FROM ratings
                UNION
                SELECT video_id FROM watch_events WHERE event_type = 'play'
            )
            """
        )
    ).scalar_one()
    feedback = {
        signal: count
        for signal, count in session.execute(
            text("SELECT signal, count(*) FROM video_feedback GROUP BY signal")
        )
    }
    dismissals = session.execute(
        text(
            """
            SELECT dismiss_reason, count(DISTINCT video_id) AS n
            FROM feed_items
            WHERE dismissed_at >= :since
            GROUP BY dismiss_reason
            ORDER BY n DESC, dismiss_reason IS NULL, dismiss_reason
            """
        ),
        {"since": since},
    )
    return Signals(
        ratings=ratings,
        watched=watched,
        more_like_this=feedback.get(MORE, 0),
        less_like_this=feedback.get(LESS, 0),
        dismissals=[DismissalCount(reason, count) for reason, count in dismissals],
    )
