"""How each subscribed channel is doing: whether its videos get watched and liked.

For pruning subscriptions that keep landing in the feed without being watched. Per
subscribed channel (`channel_health`):

- Picks: the distinct videos of the channel that were in a feed built in the last
  `PICKS_WINDOW_DAYS` days (a refresh builds another feed, so a video can be in several;
  it counts once), and how many of them were watched.
- Watched: played or rated, like the feed's own `watched` mark (`feeds.watched_video_ids`).
  A rating counts because videos can be rated without being played here.
- Last watched: when the channel's videos were last watched, counting the latest `play`
  watch event and the latest first rating over all time.
- Ratings: how many of the channel's videos are rated, and their average score.

Only videos stored in `videos` are counted, since only those are known to belong to a
channel.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core.gateway.events import format_timestamp

# How far back picks are counted, in days.
PICKS_WINDOW_DAYS = 30


@dataclass(frozen=True)
class ChannelHealth:
    channel_id: str
    last_watched_at: str | None  # ISO 8601 UTC; None if never watched
    rating_count: int
    average_score: float | None  # None without ratings
    picks: int  # distinct videos in feeds built in the window
    watched_picks: int  # of those, the ones watched (at any time)


def channel_health(
    session: Session, *, days: int = PICKS_WINDOW_DAYS, now: datetime | None = None
) -> list[ChannelHealth]:
    """The health of every subscribed channel, by title. Picks are counted over feeds
    built in the last `days` days up to `now` (default: the current time)."""
    since = format_timestamp((now or datetime.now(UTC)) - timedelta(days=days))
    channels = (
        session.execute(
            text(
                """
            SELECT p.channel_id
            FROM channel_prefs AS p JOIN channels AS c ON c.id = p.channel_id
            ORDER BY c.title COLLATE NOCASE, c.id
            """
            )
        )
        .scalars()
        .all()
    )
    rated = {
        channel_id: (count, average, last)
        for channel_id, count, average, last in session.execute(
            text(
                """
                SELECT v.channel_id, count(*), avg(r.score), max(r.rated_at)
                FROM ratings AS r JOIN videos AS v ON v.id = r.video_id
                GROUP BY v.channel_id
                """
            )
        )
    }
    played = {
        channel_id: last
        for channel_id, last in session.execute(
            text(
                """
                SELECT v.channel_id, max(e.at)
                FROM watch_events AS e JOIN videos AS v ON v.id = e.video_id
                WHERE e.event_type = 'play'
                GROUP BY v.channel_id
                """
            )
        )
    }
    picked = {
        channel_id: (picks, watched)
        for channel_id, picks, watched in session.execute(
            text(
                """
                SELECT v.channel_id, count(DISTINCT i.video_id),
                       count(DISTINCT CASE
                           WHEN EXISTS (SELECT 1 FROM ratings AS r WHERE r.video_id = i.video_id)
                             OR EXISTS (
                                 SELECT 1 FROM watch_events AS e
                                 WHERE e.video_id = i.video_id AND e.event_type = 'play'
                             )
                           THEN i.video_id
                       END)
                FROM feed_items AS i
                JOIN feeds AS f ON f.id = i.feed_id
                JOIN videos AS v ON v.id = i.video_id
                WHERE f.created_at >= :since
                GROUP BY v.channel_id
                """
            ),
            {"since": since},
        )
    }
    result = []
    for channel_id in channels:
        count, average, last_rated = rated.get(channel_id, (0, None, None))
        picks, watched = picked.get(channel_id, (0, 0))
        result.append(
            ChannelHealth(
                channel_id=channel_id,
                last_watched_at=max(
                    filter(None, (played.get(channel_id), last_rated)), default=None
                ),
                rating_count=count,
                average_score=None if average is None else float(average),
                picks=picks,
                watched_picks=watched,
            )
        )
    return result
