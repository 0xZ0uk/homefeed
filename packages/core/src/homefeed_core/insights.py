"""Weekly insights: is the feed working by the success metric (PLAN.md section 1)?

Weeks run Monday to Sunday in local time, like feed dates. For each week:

- Good rate: of the videos first rated that week (by `rated_at`), the share whose
  current score is 6 or higher (`scores.is_good`). None when nothing was rated.
- Score distribution: those same ratings counted per whole score, 1 to 10.
- Rating rate: of the distinct videos shown that week, the share that have been rated
  (at any time). "Shown" means an item of the feed of record for a date in the week, the
  latest feed built that day (as `feeds.get_feed` serves it); dismissed items count as
  shown. None when no feed was built.
- Score share: where the scores of those shown items came from, as shares of the summed
  absolute size of each kind of term (each term counted as `|term|`, so a suppressing
  tag weighs as much as a boosting one, and terms of opposite sign don't cancel):
  - model: `alpha * model`, the trained model's blended prediction (0 before a model
    existed and in rules-only feeds, whatever `model_version` says);
  - curation: `channel` and each of `tags`, the user's channel priors and tag
    subscriptions (`topics` in breakdowns stored before tags replaced them);
  - similarity: closeness to top- and bottom-tier rated videos. It is rules-based but
    learned from ratings rather than set by the user, so it is reported apart from both.
  The three shares sum to 1, or are all None when every term was 0 (or nothing shown).

Pure aggregation (`summarize_weeks`) is separate from loading (`weekly_insights`).

The discovery recap (`discovery_recap`) asks whether new channels and topics are finding
their way in. It sets two windows of `days` local days against each other: the last one,
ending today, and the one right before it. In a window:

- A channel is new when the first `play` watch event of any of its videos, over all time,
  falls in the window (the history's own rule for a watched video). Only videos stored in
  `videos` count, since only those are known to belong to a channel. New means not watched
  before, whether or not it is followed: a channel subscribed to before its first watch
  counts too.
- Tried is the number of new channels. Kept: those subscribed to now, a trial included.
  Liked: those with a video rated top tier (7 or higher) at any time.
- The new-channel share is the part of the distinct videos played in the window that come
  from channels new in it.
- A new topic is a tag that first appeared in the window among the videos watched or rated
  (a video appears when it is first played or rated; removed tag links don't count).
- Each new channel of the last window is listed with its status as it stands now, so that
  the ones worth following up (a top-tier rating on a channel I don't follow) can be
  offered a subscription, a trial included.
"""

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core.channel_hides import HideKind
from homefeed_core.feeds import local_today
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.scores import is_good, is_top_tier

DEFAULT_WEEKS = 12
MAX_WEEKS = 104


@dataclass(frozen=True)
class RatedVideo:
    video_id: str
    score: int
    rated_on: date  # local date of the first rating


@dataclass(frozen=True)
class ShownItem:
    video_id: str
    feed_date: date
    # Absolute contributions to the item's score (see the module docstring).
    model: float  # |alpha * model|
    curation: float  # |channel| + sum(|tag|)
    similarity: float  # |similarity|
    rated: bool


@dataclass(frozen=True)
class ScoreCount:
    score: int  # whole score, 1 to 10
    count: int


@dataclass(frozen=True)
class ScoreShare:
    """Shares of the absolute score contribution; they sum to 1."""

    model: float
    curation: float
    similarity: float


@dataclass(frozen=True)
class WeekInsights:
    week_start: date  # Monday
    rated_count: int
    good_count: int
    good_rate: float | None
    score_counts: list[ScoreCount]  # best score (10) first
    shown_count: int  # distinct videos shown
    shown_rated_count: int
    rating_rate: float | None
    feed_count: int  # dates with a feed
    model_feed_count: int  # of those, feeds whose items have a model contribution
    score_share: ScoreShare | None


def week_start(day: date) -> date:
    """The Monday of `day`'s week."""
    return day - timedelta(days=day.weekday())


def summarize_weeks(
    ratings: Iterable[RatedVideo], shown: Iterable[ShownItem], *, first_week: date, weeks: int
) -> list[WeekInsights]:
    """Insights for `weeks` consecutive weeks starting on Monday `first_week`, oldest
    first. Ratings and items outside those weeks are ignored."""
    starts = [first_week + timedelta(weeks=n) for n in range(weeks)]
    ratings_by_week: dict[date, list[RatedVideo]] = {start: [] for start in starts}
    shown_by_week: dict[date, list[ShownItem]] = {start: [] for start in starts}
    for rating in ratings:
        bucket = ratings_by_week.get(week_start(rating.rated_on))
        if bucket is not None:
            bucket.append(rating)
    for item in shown:
        bucket = shown_by_week.get(week_start(item.feed_date))
        if bucket is not None:
            bucket.append(item)
    return [_week(start, ratings_by_week[start], shown_by_week[start]) for start in starts]


def _week(start: date, ratings: Sequence[RatedVideo], shown: Sequence[ShownItem]) -> WeekInsights:
    good = sum(1 for rating in ratings if is_good(rating.score))
    per_score = dict.fromkeys(range(10, 0, -1), 0)
    for rating in ratings:
        per_score[rating.score] += 1
    rated_by_video: dict[str, bool] = {}
    for item in shown:
        rated_by_video[item.video_id] = rated_by_video.get(item.video_id, False) or item.rated
    shown_rated = sum(rated_by_video.values())
    model_dates = {item.feed_date for item in shown if item.model > 0}
    return WeekInsights(
        week_start=start,
        rated_count=len(ratings),
        good_count=good,
        good_rate=good / len(ratings) if ratings else None,
        score_counts=[ScoreCount(score, count) for score, count in per_score.items()],
        shown_count=len(rated_by_video),
        shown_rated_count=shown_rated,
        rating_rate=shown_rated / len(rated_by_video) if rated_by_video else None,
        feed_count=len({item.feed_date for item in shown}),
        model_feed_count=len(model_dates),
        score_share=_score_share(shown),
    )


def _score_share(shown: Sequence[ShownItem]) -> ScoreShare | None:
    model = sum(item.model for item in shown)
    curation = sum(item.curation for item in shown)
    similarity = sum(item.similarity for item in shown)
    total = model + curation + similarity
    if total == 0:
        return None
    return ScoreShare(model=model / total, curation=curation / total, similarity=similarity / total)


def weekly_insights(
    session: Session,
    *,
    weeks: int = DEFAULT_WEEKS,
    now: datetime | None = None,
    tz: tzinfo | None = None,
) -> list[WeekInsights]:
    """Insights for the last `weeks` weeks up to and including the current one, oldest
    first. `tz` is the local time zone for rating dates (default: the process's)."""
    if not 1 <= weeks <= MAX_WEEKS:
        raise ValueError(f"weeks must be between 1 and {MAX_WEEKS}")
    now = now or datetime.now(UTC)
    today = now.astimezone(tz).date() if tz is not None else local_today(now)
    first_week = week_start(today) - timedelta(weeks=weeks - 1)
    return summarize_weeks(
        load_rated_videos(session, since=first_week, tz=tz),
        load_shown_items(session, since=first_week),
        first_week=first_week,
        weeks=weeks,
    )


def load_rated_videos(
    session: Session, *, since: date, tz: tzinfo | None = None
) -> list[RatedVideo]:
    """Ratings first made on or after local date `since` (and those a day before, which
    a time zone may still put on it; `summarize_weeks` drops the rest)."""
    rows = session.execute(
        text("SELECT video_id, score, rated_at FROM ratings WHERE rated_at >= :since"),
        {"since": (since - timedelta(days=1)).isoformat()},
    )
    return [
        RatedVideo(video_id, score, datetime.fromisoformat(rated_at).astimezone(tz).date())
        for video_id, score, rated_at in rows
    ]


def load_shown_items(session: Session, *, since: date) -> list[ShownItem]:
    """Items of the feed of record (the latest feed) of each date from `since` on."""
    rows = session.execute(
        text(
            """
            WITH latest AS (
                SELECT id, date,
                       row_number() OVER (
                           PARTITION BY date ORDER BY created_at DESC, id DESC
                       ) AS rank
                FROM feeds
                WHERE date >= :since
            )
            SELECT i.video_id, l.date, i.breakdown,
                   EXISTS (SELECT 1 FROM ratings AS r WHERE r.video_id = i.video_id)
            FROM latest AS l JOIN feed_items AS i ON i.feed_id = l.id
            WHERE l.rank = 1
            """
        ),
        {"since": since.isoformat()},
    )
    items: list[ShownItem] = []
    for video_id, day, breakdown_json, rated in rows:
        breakdown = json.loads(breakdown_json)
        items.append(
            ShownItem(
                video_id=video_id,
                feed_date=date.fromisoformat(day),
                model=abs(breakdown.get("alpha", 0.0) * breakdown.get("model", 0.0)),
                curation=abs(breakdown.get("channel", 0.0))
                + sum(
                    abs(value)
                    for value in breakdown.get("tags", breakdown.get("topics", {})).values()
                ),
                similarity=abs(breakdown.get("similarity", 0.0)),
                rated=bool(rated),
            )
        )
    return items


DEFAULT_RECAP_DAYS = 7
MAX_RECAP_DAYS = 90
# How many new topics a recap lists, the most watched first; the count has all of them.
MAX_RECAP_TOPICS = 12

# Where a channel stands: subscribed to, subscribed to on a trial, hidden (and not
# subscribed to) or none of these.
ChannelStatus = Literal["subscribed", "trial", "hidden", "not_followed"]


@dataclass(frozen=True)
class DiscoveredChannel:
    """A channel first watched in the window, as it stands now."""

    channel_id: str
    title: str
    handle: str | None
    thumbnail_url: str | None
    videos_watched: int  # distinct videos of the channel played in the window
    rating_count: int  # the channel's rated videos, rated at any time
    average_score: float | None  # None without ratings
    top_score: int | None  # the best of those ratings
    status: ChannelStatus
    trial_until: str | None  # ISO 8601 UTC; set while on trial
    hide_kind: HideKind | None  # how it is hidden, while its status is "hidden"
    follow_up: bool  # a top-tier rating on a channel I don't follow


@dataclass(frozen=True)
class DiscoveredTopic:
    slug: str
    label: str
    videos: int  # watched or rated videos carrying the tag


@dataclass(frozen=True)
class RecapWindow:
    """One window of the recap: local dates, both ends included."""

    start: date
    end: date
    new_channels: int  # tried
    kept_channels: int  # of those, subscribed to now (a trial included)
    liked_channels: int  # of those, with a top-tier rating
    videos_watched: int  # distinct videos played in the window
    new_channel_videos: int  # of those, the ones from channels new in the window
    new_channel_share: float | None  # None when nothing was watched
    new_topics: int


@dataclass(frozen=True)
class DiscoveryRecap:
    days: int
    current: RecapWindow
    previous: RecapWindow
    # The current window's new channels, the best rated first, then the unrated ones by
    # most videos watched.
    channels: list[DiscoveredChannel]
    # The current window's new topics, the most watched first, at most `MAX_RECAP_TOPICS`.
    topics: list[DiscoveredTopic]


@dataclass(frozen=True)
class _Window:
    start: date  # first local day
    end: date  # last local day
    since: str  # when the first day begins, as a stored (UTC) time
    until: str  # when the day after the last begins

    def holds(self, at: str) -> bool:
        return self.since <= at < self.until


@dataclass(frozen=True)
class _FirstWatch:
    channel_id: str
    title: str
    handle: str | None
    thumbnail_url: str | None
    first_at: str  # ISO 8601 UTC; the channel's first play, over all time
    status: ChannelStatus
    trial_until: str | None
    hide_kind: HideKind | None


@dataclass(frozen=True)
class _TopicSighting:
    slug: str
    label: str
    first_at: str  # ISO 8601 UTC; when a video carrying the tag was first played or rated
    videos: int


def channel_status(
    *, subscribed: bool, trial_until: str | None, hide_kind: HideKind | None
) -> ChannelStatus:
    """Where a channel stands. A subscription decides over a hide, as subscribing clears
    the hide."""
    if subscribed:
        return "trial" if trial_until else "subscribed"
    return "hidden" if hide_kind else "not_followed"


def discovery_recap(
    session: Session,
    *,
    today: date,
    days: int = DEFAULT_RECAP_DAYS,
    tz: tzinfo | None = None,
) -> DiscoveryRecap:
    """The last `days` local days up to and including `today`, set against the `days`
    before them (see the module docstring). `tz` is the local time zone the days are in
    (default: the process's)."""
    if not 1 <= days <= MAX_RECAP_DAYS:
        raise ValueError(f"days must be between 1 and {MAX_RECAP_DAYS}")
    last = _window(today - timedelta(days=days - 1), today, tz)
    before = _window(last.start - timedelta(days=days), last.start - timedelta(days=1), tz)
    first_watches = _load_first_watches(session, since=before.since, until=last.until)
    played = _load_played(session, since=before.since, until=last.until, split=last.since)
    ratings = _load_channel_ratings(session)
    sightings = _load_topic_sightings(session, since=before.since, until=last.until)

    def summarize(window: _Window, *, is_last: bool) -> tuple[RecapWindow, list[DiscoveredChannel]]:
        new = [watch for watch in first_watches if window.holds(watch.first_at)]
        videos = {(video, channel) for video, channel, recent in played if recent == is_last}
        videos_by_channel: dict[str, int] = {}
        for _, channel in videos:
            videos_by_channel[channel] = videos_by_channel.get(channel, 0) + 1
        channels = [_discovered(watch, videos_by_channel, ratings) for watch in new]
        new_ids = {channel.channel_id for channel in channels}
        new_videos = sum(1 for _, channel in videos if channel in new_ids)
        return (
            RecapWindow(
                start=window.start,
                end=window.end,
                new_channels=len(channels),
                kept_channels=sum(c.status in ("subscribed", "trial") for c in channels),
                liked_channels=sum(
                    c.top_score is not None and is_top_tier(c.top_score) for c in channels
                ),
                videos_watched=len(videos),
                new_channel_videos=new_videos,
                new_channel_share=new_videos / len(videos) if videos else None,
                new_topics=sum(window.holds(sighting.first_at) for sighting in sightings),
            ),
            channels,
        )

    current, channels = summarize(last, is_last=True)
    previous, _ = summarize(before, is_last=False)
    topics = [
        DiscoveredTopic(sighting.slug, sighting.label, sighting.videos)
        for sighting in sightings
        if last.holds(sighting.first_at)
    ]
    return DiscoveryRecap(
        days=days,
        current=current,
        previous=previous,
        channels=sorted(
            channels,
            key=lambda c: (
                c.average_score is None,
                -(c.average_score or 0.0),
                -c.videos_watched,
                c.title.casefold(),
                c.channel_id,
            ),
        ),
        topics=topics[:MAX_RECAP_TOPICS],
    )


def _window(start: date, end: date, tz: tzinfo | None) -> _Window:
    return _Window(start, end, _day_start(start, tz), _day_start(end + timedelta(days=1), tz))


def _day_start(day: date, tz: tzinfo | None) -> str:
    """When local `day` begins, as a stored time: ISO 8601 UTC, so that it compares with
    them as text. Without `tz` the day is in the process's time zone."""
    return format_timestamp(datetime.combine(day, time.min, tzinfo=tz))


def _discovered(
    watch: _FirstWatch,
    videos_by_channel: dict[str, int],
    ratings: dict[str, tuple[int, float, int]],
) -> DiscoveredChannel:
    count, average, top = ratings.get(watch.channel_id, (0, None, None))
    return DiscoveredChannel(
        channel_id=watch.channel_id,
        title=watch.title,
        handle=watch.handle,
        thumbnail_url=watch.thumbnail_url,
        videos_watched=videos_by_channel.get(watch.channel_id, 0),
        rating_count=count,
        average_score=average,
        top_score=top,
        status=watch.status,
        trial_until=watch.trial_until,
        hide_kind=watch.hide_kind,
        follow_up=(
            watch.status in ("hidden", "not_followed") and top is not None and is_top_tier(top)
        ),
    )


def _load_first_watches(session: Session, *, since: str, until: str) -> list[_FirstWatch]:
    """Channels whose first play, over all time, is at or after `since` and before
    `until`, with where each stands now."""
    rows = session.execute(
        text(
            """
            SELECT c.id, c.title, c.handle, c.thumbnail_url, f.first_at,
                   p.channel_id IS NOT NULL, p.trial_until, h.kind
            FROM (
                SELECT v.channel_id AS channel_id, min(e.at) AS first_at
                FROM watch_events AS e JOIN videos AS v ON v.id = e.video_id
                WHERE e.event_type = 'play'
                GROUP BY v.channel_id
            ) AS f
            JOIN channels AS c ON c.id = f.channel_id
            LEFT JOIN channel_prefs AS p ON p.channel_id = c.id
            LEFT JOIN channel_hides AS h ON h.channel_id = c.id
            WHERE f.first_at >= :since AND f.first_at < :until
            """
        ),
        {"since": since, "until": until},
    )
    return [
        _FirstWatch(
            channel_id=channel_id,
            title=title,
            handle=handle,
            thumbnail_url=thumbnail_url,
            first_at=first_at,
            status=channel_status(
                subscribed=bool(subscribed), trial_until=trial_until, hide_kind=hide_kind
            ),
            trial_until=trial_until,
            hide_kind=None if subscribed else hide_kind,
        )
        for (
            channel_id,
            title,
            handle,
            thumbnail_url,
            first_at,
            subscribed,
            trial_until,
            hide_kind,
        ) in rows
    ]


def _load_played(
    session: Session, *, since: str, until: str, split: str
) -> list[tuple[str, str, bool]]:
    """The videos played at or after `since` and before `until`, as (video id, channel
    id, played at or after `split`): one row per video and side of `split`, so a video
    played on both sides is in both."""
    rows = session.execute(
        text(
            """
            SELECT DISTINCT e.video_id, v.channel_id, e.at >= :split
            FROM watch_events AS e JOIN videos AS v ON v.id = e.video_id
            WHERE e.event_type = 'play' AND e.at >= :since AND e.at < :until
            """
        ),
        {"since": since, "until": until, "split": split},
    )
    return [(video_id, channel_id, bool(recent)) for video_id, channel_id, recent in rows]


def _load_channel_ratings(session: Session) -> dict[str, tuple[int, float, int]]:
    """Per channel with rated videos: how many, their average score and the best."""
    return {
        channel_id: (count, float(average), top)
        for channel_id, count, average, top in session.execute(
            text(
                """
                SELECT v.channel_id, count(*), avg(r.score), max(r.score)
                FROM ratings AS r JOIN videos AS v ON v.id = r.video_id
                GROUP BY v.channel_id
                """
            )
        )
    }


def _load_topic_sightings(session: Session, *, since: str, until: str) -> list[_TopicSighting]:
    """Tags whose first appearance among played or rated videos is at or after `since` and
    before `until`, the most watched first. A video appears when it is first played or
    rated."""
    rows = session.execute(
        text(
            """
            WITH seen AS (
                SELECT video_id, min(at) AS at FROM (
                    SELECT video_id, at FROM watch_events
                    WHERE event_type = 'play' AND at < :until
                    UNION ALL
                    SELECT video_id, rated_at FROM ratings WHERE rated_at < :until
                )
                GROUP BY video_id
            )
            SELECT t.slug, t.label, min(s.at) AS first_at, count(*) AS videos
            FROM video_tags AS vt
            JOIN tags AS t ON t.id = vt.tag_id
            JOIN seen AS s ON s.video_id = vt.video_id
            WHERE vt.removed_at IS NULL
            GROUP BY t.id
            HAVING min(s.at) >= :since
            ORDER BY videos DESC, t.label COLLATE NOCASE, t.slug
            """
        ),
        {"since": since, "until": until},
    )
    return [_TopicSighting(slug, label, first_at, videos) for slug, label, first_at, videos in rows]
