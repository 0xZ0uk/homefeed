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

from homefeed_core import candidates, enricher, feeds, poller, smoke_test, trainer
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.external_sources import ExternalSourcesSource
from homefeed_core.gateway import create_gateway
from homefeed_core.tag_discovery import TagDiscoverySource

logger = logging.getLogger(__name__)

# How often the worker looks for subscribed channels whose RSS feed is due. Each
# channel has its own schedule and backoff (see homefeed_core.poller); this only bounds
# how late a due channel is picked up.
POLL_CHECK_MINUTES = 10
# How often new candidates are enriched, so the daily feed build finds most of them
# already done. The feed build enriches whatever is left before ranking.
ENRICH_CHECK_MINUTES = 30
# How often the worker looks for external sources (subreddits, feeds, link pages) that
# are due; each has its own schedule (hourly, daily or weekly) and backoff.
EXTERNAL_SOURCES_CHECK_MINUTES = 15
# How often the worker looks for subscribed tags that are due a YouTube search (once a day
# each, capped per day; see homefeed_core.tag_discovery).
TAG_DISCOVERY_CHECK_MINUTES = 60


# The feed job polls too; this keeps it and the poll job from polling at the same time.
_poll_lock = threading.Lock()
# Likewise for the feed job's and the enrich job's enrichment.
_enrich_lock = threading.Lock()


def poll_subscriptions() -> None:
    """Fetch due subscription feeds and record new uploads as candidates."""
    with _poll_lock:
        new = poller.poll_due_channels()
    logger.info("Subscription poll found %d new candidates", len(new))


def generate_candidates() -> None:
    """Run the candidate sources other than subscriptions (related videos of top-tier
    ratings, due saved searches); a failing source is logged and skipped."""
    report = candidates.generate()
    for source, video_ids in report.new.items():
        logger.info("Candidate source %r found %d new candidates", source, len(video_ids))
    for source, error in report.failed.items():
        logger.warning("Candidate source %r failed: %s", source, error)


def gather_candidates() -> None:
    """Poll due subscriptions, then run the other candidate sources."""
    try:
        poll_subscriptions()
    except Exception:
        logger.exception("Polling subscriptions failed; running the other sources anyway")
    generate_candidates()


def enrich_candidates() -> None:
    """Compute features (metadata, transcript excerpt, embedding) for new candidates."""
    with _enrich_lock:
        report = enricher.enrich_candidates()
    logger.info(
        "Enriched %d candidates (%d up to date, %d failed)",
        len(report.enriched),
        len(report.cached),
        len(report.failed),
    )


def fetch_external_sources() -> None:
    """Fetch due external sources and record the YouTube videos they link to."""
    sessions = get_session_factory()
    source = ExternalSourcesSource(sessions, create_gateway(sessions))
    report = candidates.generate([source], sessions=sessions)
    for name, video_ids in report.new.items():
        logger.info("Candidate source %r found %d new candidates", name, len(video_ids))
    for name, error in report.failed.items():
        logger.warning("Candidate source %r failed: %s", name, error)


def discover_tag_videos() -> None:
    """Search YouTube for the subscribed tags that are due and record the new videos."""
    sessions = get_session_factory()
    source = TagDiscoverySource(
        sessions,
        create_gateway(sessions),
        per_tag_per_day=get_settings().tag_discovery_per_day,
    )
    report = candidates.generate([source], sessions=sessions)
    for name, video_ids in report.new.items():
        logger.info("Candidate source %r found %d new candidates", name, len(video_ids))
    for name, error in report.failed.items():
        logger.warning("Candidate source %r failed: %s", name, error)


def build_daily_feed() -> None:
    """Gather candidates (subscriptions, related videos), enrich them, then rank and
    compose today's feed (poll → candidates → enrich → rank → compose)."""
    feed = feeds.refresh_feed(poll=gather_candidates, enrich=enrich_candidates)
    logger.info("Built the feed for %s with %d items", feed.date, len(feed.items))


def train_model() -> None:
    """Train a ranking model on the ratings so far and promote it unless it does worse
    than the active one; skipped while there are too few ratings (see
    homefeed_core.trainer, which logs the outcome)."""
    trainer.run_nightly_training()


def run_gateway_smoke_test() -> None:
    """Run the live Gateway smoke test against real YouTube; the outcome is recorded in
    `extractor_events` for the status page (see homefeed_core.smoke_test)."""
    report = smoke_test.run_live_smoke_test()
    if report.success:
        logger.info("Gateway smoke test passed (%d checks)", len(report.checks))
    else:
        logger.warning("Gateway smoke test failed: %s", report.summary())


def build_scheduler(
    poll: Callable[[], None] = poll_subscriptions,
    enrich: Callable[[], None] = enrich_candidates,
    build_feed: Callable[[], None] = build_daily_feed,
    train: Callable[[], None] = train_model,
    smoke: Callable[[], None] = run_gateway_smoke_test,
    *,
    feed_refresh_time: time | None = None,
    model_training_time: time | None = None,
    gateway_smoke_test_time: time | None = None,
    build_feed_now: bool = False,
) -> BlockingScheduler:
    """Create the scheduler with all worker jobs registered.

    The daily feed runs at `feed_refresh_time` (default `FEED_REFRESH_TIME`) and model
    training at `model_training_time` (default `MODEL_TRAINING_TIME`), both in the
    process's local time zone; `build_feed_now` also builds the feed right away. The
    live Gateway smoke test is opt-in: it runs daily at `gateway_smoke_test_time`
    (default `GATEWAY_SMOKE_TEST_TIME`) and isn't scheduled when neither is set.
    """
    settings = get_settings()
    refresh = feed_refresh_time or settings.feed_refresh_time
    training = model_training_time or settings.model_training_time
    smoke_time = gateway_smoke_test_time or settings.gateway_smoke_test_time
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
        enrich,
        IntervalTrigger(minutes=ENRICH_CHECK_MINUTES, timezone=UTC),
        id="enrich_candidates",
        name="Enrich candidates",
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
    scheduler.add_job(
        train,
        CronTrigger(hour=training.hour, minute=training.minute),  # local time zone
        id="train_model",
        name="Train the ranking model",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
    )
    scheduler.add_job(
        fetch_external_sources,
        IntervalTrigger(minutes=EXTERNAL_SOURCES_CHECK_MINUTES, timezone=UTC),
        id="fetch_external_sources",
        name="Fetch external sources",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
    )
    scheduler.add_job(
        discover_tag_videos,
        IntervalTrigger(minutes=TAG_DISCOVERY_CHECK_MINUTES, timezone=UTC),
        id="discover_tag_videos",
        name="Discover videos for subscribed tags",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
    )
    if smoke_time is not None:
        scheduler.add_job(
            smoke,
            CronTrigger(hour=smoke_time.hour, minute=smoke_time.minute),  # local time zone
            id="gateway_smoke_test",
            name="Live Gateway smoke test",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=None,
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
