"""Weekly insights: is the feed working by the success metric (PLAN.md section 1)?

Weeks run Monday to Sunday in local time, like feed dates. For each week:

- Good rate: of the videos first rated that week (by `rated_at`), the share whose
  current score is 5.5 or higher (`scores.is_good`). None when nothing was rated.
- Score distribution: those same ratings counted per whole score, 1 to 10
  (`scores.score_bucket`: 6.5 counts as 7).
- Rating rate: of the distinct videos shown that week, the share that have been rated
  (at any time). "Shown" means an item of the feed of record for a date in the week, the
  latest feed built that day (as `feeds.get_feed` serves it); dismissed items count as
  shown. None when no feed was built.
- Score share: where the scores of those shown items came from, as shares of the summed
  absolute size of each kind of term (each term counted as `|term|`, so a suppressing
  topic weighs as much as a boosting one, and terms of opposite sign don't cancel):
  - model: `alpha * model`, the trained model's blended prediction (0 before a model
    existed and in rules-only feeds, whatever `model_version` says);
  - curation: `channel` and each of `topics`, the user's channel priors and topics;
  - similarity: closeness to top- and bottom-tier rated videos. It is rules-based but
    learned from ratings rather than set by the user, so it is reported apart from both.
  The three shares sum to 1, or are all None when every term was 0 (or nothing shown).

Pure aggregation (`summarize_weeks`) is separate from loading (`weekly_insights`).
"""

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, tzinfo

from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core.feeds import local_today
from homefeed_core.scores import is_good, score_bucket

DEFAULT_WEEKS = 12
MAX_WEEKS = 104


@dataclass(frozen=True)
class RatedVideo:
    video_id: str
    score: float
    rated_on: date  # local date of the first rating


@dataclass(frozen=True)
class ShownItem:
    video_id: str
    feed_date: date
    # Absolute contributions to the item's score (see the module docstring).
    model: float  # |alpha * model|
    curation: float  # |channel| + sum(|topic|)
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
        per_score[score_bucket(rating.score)] += 1
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
                + sum(abs(value) for value in breakdown.get("topics", {}).values()),
                similarity=abs(breakdown.get("similarity", 0.0)),
                rated=bool(rated),
            )
        )
    return items
