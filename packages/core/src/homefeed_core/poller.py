"""Polling subscribed channels' RSS feeds into the candidate pool.

`poll_due_channels()` fetches the feed of every subscribed, unmuted channel whose next
poll time has come, stores the listed videos in `videos` and records them as
`subscription` candidates. Each channel keeps its own schedule in `channel_polls`: it
is polled again `interval` (plus jitter) after a success, and after failures it backs
off exponentially, up to `max_backoff`, so a broken or throttled channel never holds
up the others.

RSS gives a video's id, title, description, publish time, thumbnail, view count and
whether it is a Short (its link is a /shorts/ URL), but not its duration or live
status. Those are left NULL here and filled in later through `Gateway.get_video`.
"""

import logging
import random
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import candidates
from homefeed_core.curation import muted_sql
from homefeed_core.db import get_session_factory
from homefeed_core.gateway import FeedFetcher, GatewayError, create_feed_fetcher
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.gateway.urls import CHANNEL_ID, VIDEO_ID

logger = logging.getLogger(__name__)

VideoId = str

DEFAULT_BATCH_SIZE = 100

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}


class FeedParseError(ValueError):
    """The response is not a YouTube channel feed."""


@dataclass(frozen=True)
class FeedEntry:
    video_id: str
    channel_id: str
    title: str
    published_at: datetime | None = None
    updated_at: datetime | None = None
    description: str | None = None
    thumbnail_url: str | None = None
    view_count: int | None = None
    is_short: bool = False


@dataclass(frozen=True)
class ChannelFeed:
    channel_id: str | None
    title: str | None
    entries: list[FeedEntry]  # newest first, as YouTube lists them


@dataclass(frozen=True)
class PollSchedule:
    """When a channel is polled next.

    After a success: `interval`, stretched by up to `jitter` (a fraction) so channels
    subscribed together drift apart. After `n` consecutive failures:
    `retry_after * 2 ** (n - 1)`, capped at `max_backoff`.
    """

    interval: timedelta = timedelta(hours=1)
    jitter: float = 0.1
    retry_after: timedelta = timedelta(minutes=15)
    max_backoff: timedelta = timedelta(hours=24)

    def after_success(self, now: datetime, rng: random.Random) -> datetime:
        return now + self.interval * (1 + self.jitter * rng.random())

    def after_failure(self, now: datetime, failures: int) -> datetime:
        return now + min(self.retry_after * 2 ** (failures - 1), self.max_backoff)


def parse_feed(xml: bytes) -> ChannelFeed:
    """Parse a channel's RSS (Atom) feed. Raises `FeedParseError` if it isn't one."""
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise FeedParseError(f"Not XML: {error}") from error
    if root.tag != f"{{{_NS['atom']}}}feed":
        raise FeedParseError(f"Not an Atom feed (root element {root.tag!r})")
    channel_id = _text(root, "yt:channelId")
    if channel_id and not channel_id.startswith("UC"):
        channel_id = "UC" + channel_id  # the feed header drops the prefix
    entries = [entry for node in root.findall("atom:entry", _NS) if (entry := _entry(node))]
    return ChannelFeed(channel_id=channel_id, title=_text(root, "atom:title"), entries=entries)


def poll_due_channels(
    *,
    sessions: sessionmaker[Session] | None = None,
    fetch: FeedFetcher | None = None,
    schedule: PollSchedule | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
    rng: random.Random | None = None,
) -> list[VideoId]:
    """Poll up to `batch_size` due channels, most overdue first.

    Returns the ids of videos that became candidates (new to the pool), newest first
    per channel. A channel whose feed can't be fetched or parsed is rescheduled with
    backoff and the run continues.
    """
    sessions = sessions or get_session_factory()
    fetch = fetch or create_feed_fetcher(sessions)
    schedule = schedule or PollSchedule()
    rng = rng or random.Random()

    with sessions() as session:
        due = due_channel_ids(session, now(), limit=batch_size)
    new_ids: list[VideoId] = []
    for channel_id in due:
        try:
            feed = parse_feed(fetch(channel_id))
        except (GatewayError, FeedParseError) as error:
            logger.warning("Polling channel %s failed: %s", channel_id, error)
            with sessions.begin() as session:
                _record_failure(session, channel_id, now(), str(error), schedule)
            continue
        with sessions.begin() as session:
            new_ids += _store_feed(session, channel_id, feed, now())
            _record_success(session, channel_id, now(), schedule, rng)
    if due:
        logger.info("Polled %d channels, %d new candidates", len(due), len(new_ids))
    return new_ids


def due_channel_ids(session: Session, now: datetime, *, limit: int | None = None) -> list[str]:
    """Subscribed, unmuted channels due for a poll; never-polled ones first. A channel
    muted until a time still ahead is skipped until it runs out."""
    rows = session.execute(
        text(
            f"""
            SELECT p.channel_id
            FROM channel_prefs AS p
            LEFT JOIN channel_polls AS s ON s.channel_id = p.channel_id
            WHERE NOT {muted_sql("p")} AND (s.next_poll_at IS NULL OR s.next_poll_at <= :now)
            ORDER BY s.next_poll_at IS NOT NULL, s.next_poll_at, p.subscribed_at, p.channel_id
            LIMIT :limit
            """
        ),
        {"now": format_timestamp(now), "limit": -1 if limit is None else limit},
    )
    return list(rows.scalars())


def _store_feed(session: Session, channel_id: str, feed: ChannelFeed, now: datetime) -> list[str]:
    entries = [entry for entry in feed.entries if entry.channel_id == channel_id]
    for entry in entries:
        _upsert_video(session, entry)
    return candidates.record(
        session,
        [entry.video_id for entry in entries],
        source=candidates.SUBSCRIPTION,
        source_detail=channel_id,
        now=now,
    )


def _upsert_video(session: Session, entry: FeedEntry) -> None:
    """Store what the feed knows, keeping richer metadata already fetched elsewhere."""
    session.execute(
        text(
            """
            INSERT INTO videos (id, channel_id, title, description, published_at,
                                thumbnail_url, is_short, view_count)
            VALUES (:id, :channel_id, :title, :description, :published_at,
                    :thumbnail_url, :is_short, :view_count)
            ON CONFLICT (id) DO UPDATE SET
                title = excluded.title,
                description = coalesce(excluded.description, videos.description),
                published_at = coalesce(excluded.published_at, videos.published_at),
                thumbnail_url = coalesce(videos.thumbnail_url, excluded.thumbnail_url),
                is_short = max(videos.is_short, excluded.is_short),
                view_count = coalesce(excluded.view_count, videos.view_count),
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
            """
        ),
        {
            "id": entry.video_id,
            "channel_id": entry.channel_id,
            "title": entry.title,
            "description": entry.description,
            "published_at": format_timestamp(entry.published_at) if entry.published_at else None,
            "thumbnail_url": entry.thumbnail_url,
            "is_short": int(entry.is_short),
            "view_count": entry.view_count,
        },
    )


def _record_success(
    session: Session, channel_id: str, now: datetime, schedule: PollSchedule, rng: random.Random
) -> None:
    session.execute(
        text(
            """
            INSERT INTO channel_polls (channel_id, next_poll_at, last_polled_at,
                                       last_success_at, consecutive_failures, last_error)
            VALUES (:channel_id, :next_poll_at, :now, :now, 0, NULL)
            ON CONFLICT (channel_id) DO UPDATE SET
                next_poll_at = excluded.next_poll_at,
                last_polled_at = excluded.last_polled_at,
                last_success_at = excluded.last_success_at,
                consecutive_failures = 0,
                last_error = NULL
            """
        ),
        {
            "channel_id": channel_id,
            "next_poll_at": format_timestamp(schedule.after_success(now, rng)),
            "now": format_timestamp(now),
        },
    )


def _record_failure(
    session: Session, channel_id: str, now: datetime, error: str, schedule: PollSchedule
) -> None:
    failures = 1 + (
        session.execute(
            text("SELECT consecutive_failures FROM channel_polls WHERE channel_id = :id"),
            {"id": channel_id},
        ).scalar_one_or_none()
        or 0
    )
    session.execute(
        text(
            """
            INSERT INTO channel_polls (channel_id, next_poll_at, last_polled_at,
                                       consecutive_failures, last_error)
            VALUES (:channel_id, :next_poll_at, :now, :failures, :error)
            ON CONFLICT (channel_id) DO UPDATE SET
                next_poll_at = excluded.next_poll_at,
                last_polled_at = excluded.last_polled_at,
                consecutive_failures = excluded.consecutive_failures,
                last_error = excluded.last_error
            """
        ),
        {
            "channel_id": channel_id,
            "next_poll_at": format_timestamp(schedule.after_failure(now, failures)),
            "now": format_timestamp(now),
            "failures": failures,
            "error": error,
        },
    )


def _entry(node: ET.Element) -> FeedEntry | None:
    video_id = _text(node, "yt:videoId")
    channel_id = _text(node, "yt:channelId")
    if not video_id or not VIDEO_ID.match(video_id):
        return None
    if not channel_id or not CHANNEL_ID.match(channel_id):
        return None
    link = node.find("atom:link[@rel='alternate']", _NS)
    href = link.get("href", "") if link is not None else ""
    thumbnail = node.find("media:group/media:thumbnail", _NS)
    statistics = node.find("media:group/media:community/media:statistics", _NS)
    views = statistics.get("views") if statistics is not None else None
    return FeedEntry(
        video_id=video_id,
        channel_id=channel_id,
        title=_text(node, "atom:title") or _text(node, "media:group/media:title") or "",
        published_at=_datetime(_text(node, "atom:published")),
        updated_at=_datetime(_text(node, "atom:updated")),
        description=_text(node, "media:group/media:description") or None,
        thumbnail_url=thumbnail.get("url") if thumbnail is not None else None,
        view_count=int(views) if views and views.isdigit() else None,
        is_short="/shorts/" in href,
    )


def _text(node: ET.Element, path: str) -> str | None:
    found = node.find(path, _NS)
    if found is None or found.text is None:
        return None
    return found.text.strip()


def _datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
