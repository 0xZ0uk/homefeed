import logging
import signal
import threading
from collections.abc import Callable
from datetime import UTC, datetime, time
from types import FrameType

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.util import undefined

from homefeed_core import feeds, poller
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory

logger = logging.getLogger(__name__)

# How often the worker looks for subscribed channels whose RSS feed is due. Each
# channel has its own schedule and backoff (see homefeed_core.poller); this only bounds
# how late a due channel is picked up.
POLL_CHECK_MINUTES = 10


# The feed job polls too; this keeps it and the poll job from polling at the same time.
_poll_lock = threading.Lock()


def poll_subscriptions() -> None:
    """Fetch due subscription feeds and record new uploads as candidates."""
    with _poll_lock:
        new = poller.poll_due_channels()
    logger.info("Subscription poll found %d new candidates", len(new))


def build_daily_feed() -> None:
    """Poll due subscriptions, then rank and compose today's feed (poll → candidates →
    rank → compose)."""
    feed = feeds.refresh_feed(poll=poll_subscriptions)
    logger.info("Built the feed for %s with %d items", feed.date, len(feed.items))


def build_scheduler(
    poll: Callable[[], None] = poll_subscriptions,
    build_feed: Callable[[], None] = build_daily_feed,
    *,
    feed_refresh_time: time | None = None,
    build_feed_now: bool = False,
) -> BlockingScheduler:
    """Create the scheduler with all worker jobs registered.

    The daily feed runs at `feed_refresh_time` (default `FEED_REFRESH_TIME`) in the
    process's local time zone; `build_feed_now` also runs it right away.
    """
    refresh = feed_refresh_time or get_settings().feed_refresh_time
    scheduler = BlockingScheduler(timezone=UTC)
    scheduler.add_job(
        poll,
        IntervalTrigger(minutes=POLL_CHECK_MINUTES, timezone=UTC),
        id="poll_subscriptions",
        name="Poll subscriptions",
        next_run_time=datetime.now(UTC),  # also poll right away on startup
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
    )
    scheduler.add_job(
        build_feed,
        CronTrigger(hour=refresh.hour, minute=refresh.minute),  # local time zone
        id="daily_feed",
        name="Build the daily feed",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
        next_run_time=datetime.now(UTC) if build_feed_now else undefined,
    )
    return scheduler


def run() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    sessions = get_session_factory()  # create and migrate the database before scheduling
    with sessions() as session:
        missing_today = feeds.get_feed(session, feeds.local_today()) is None
    # A worker started after FEED_REFRESH_TIME (or after downtime) builds today's feed now.
    scheduler = build_scheduler(build_feed_now=missing_today)

    def stop(signum: int, _frame: FrameType | None) -> None:
        logger.info("Received %s, shutting down", signal.Signals(signum).name)
        scheduler.shutdown()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    logger.info("Worker starting (database: %s)", settings.database_path)
    scheduler.start()
    logger.info("Worker stopped")
