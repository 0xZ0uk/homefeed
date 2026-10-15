"""The scheduled jobs: what runs when, on an APScheduler scheduler.

`register_jobs` puts the candidate pipeline (see `homefeed_core.pipeline`) and the
nightly jobs on any scheduler; `build_scheduler` and `start_background_scheduler` wire
it for the two processes that run them: the worker (`homefeed_worker.scheduler.run`,
the blocking entry point) and, when `RUN_WORKER_IN_API` is set, a background scheduler
inside the API process. Job times and their time zone come from the user
settings; `sync_schedule` re-reads them every minute so a change applies without a
restart.
"""

import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.util import undefined

from homefeed_core import pipeline, smoke_test, trainer, trials, ytdlp_updates
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.feeds import get_feed, local_today
from homefeed_core.user_settings import UserSettings, get_user_settings, load_user_settings

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
# How often the user settings are read again, so a feed or training time (or time zone)
# changed on the settings screen applies without a restart, whichever process runs the jobs.
SETTINGS_CHECK_MINUTES = 1
# The trial job runs this long before the daily feed build, so a channel whose trial ended
# is already gone when that day's feed is ranked.
TRIAL_SETTLE_LEAD = timedelta(minutes=5)
# How often the worker looks for a newer yt-dlp when YTDLP_AUTO_UPDATE is on (it also
# looks shortly after startup).
YTDLP_UPDATE_HOURS = 24
YTDLP_UPDATE_STARTUP_DELAY_MINUTES = 2


def train_model() -> None:
    """Train a ranking model on the ratings so far and promote it unless it does worse
    than the active one; skipped while there are too few ratings (see
    homefeed_core.trainer, which logs the outcome)."""
    trainer.run_nightly_training()


def settle_channel_trials() -> None:
    """Decide the channel trials that have run out: keep a channel when a video of it was
    rated top tier during its trial, else unsubscribe and record a "Not now" hide (see
    homefeed_core.trials)."""
    with get_session_factory().begin() as session:
        report = trials.settle_trials(session)
    logger.info("Channel trials settled: %d kept, %d ended", len(report.kept), len(report.ended))


def run_gateway_smoke_test() -> None:
    """Run the live Gateway smoke test against real YouTube; the outcome is recorded in
    `extractor_events` for the status page (see homefeed_core.smoke_test)."""
    report = smoke_test.run_live_smoke_test()
    if report.success:
        logger.info("Gateway smoke test passed (%d checks)", len(report.checks))
    else:
        logger.warning("Gateway smoke test failed: %s", report.summary())


def daily_triggers(user: UserSettings, smoke_time: time | None) -> dict[str, CronTrigger]:
    """The daily jobs' triggers, by job id: the feed and training at the user settings'
    times, the channel trials just before the feed, and the smoke test (if `smoke_time`
    is set), all in the user's time zone."""
    triggers = {
        "daily_feed": _daily(user.feed_refresh_time, user.tz),
        "settle_trials": _daily(_before(user.feed_refresh_time, TRIAL_SETTLE_LEAD), user.tz),
        "train_model": _daily(user.model_training_time, user.tz),
    }
    if smoke_time is not None:
        triggers["gateway_smoke_test"] = _daily(smoke_time, user.tz)
    return triggers


def _before(at: time, lead: timedelta) -> time:
    """The time of day `lead` before `at`, wrapping around midnight."""
    return (datetime.combine(date(2000, 1, 1), at) - lead).time()


def _daily(at: time, tz: tzinfo | None) -> CronTrigger:
    # A None time zone is the system's (APScheduler asks tzlocal).
    return CronTrigger(hour=at.hour, minute=at.minute, timezone=tz)


def sync_schedule(
    scheduler: BaseScheduler, *, smoke_time: time | None, user: UserSettings | None = None
) -> None:
    """Reschedule the daily jobs whose time or time zone changed in the user settings
    (default: read now). Run every `SETTINGS_CHECK_MINUTES`."""
    user = user or load_user_settings()
    for job_id, trigger in daily_triggers(user, smoke_time).items():
        job = scheduler.get_job(job_id)
        if job is not None and repr(job.trigger) != repr(trigger):
            scheduler.reschedule_job(job_id, trigger=trigger)
            logger.info("Rescheduled %r: %s", job.name, trigger)


def update_ytdlp() -> None:
    """Install a newer yt-dlp release into DATA_DIR/ytdlp if there is one; it takes effect
    on the next restart (see homefeed_core.ytdlp_updates). Failures are logged, not raised."""
    try:
        version = ytdlp_updates.update()
    except ytdlp_updates.YtDlpUpdateError as error:
        logger.warning("yt-dlp update failed: %s", error)
        return
    if version is not None:
        logger.info("yt-dlp %s installed; restart Homefeed to use it", version)


def register_jobs(
    scheduler: BaseScheduler,
    poll: Callable[[], None] = pipeline.poll_subscriptions,
    enrich: Callable[[], None] = pipeline.enrich_candidates,
    build_feed: Callable[[], None] = pipeline.build_daily_feed,
    train: Callable[[], None] = train_model,
    settle: Callable[[], None] = settle_channel_trials,
    smoke: Callable[[], None] = run_gateway_smoke_test,
    ytdlp_update: Callable[[], None] = update_ytdlp,
    *,
    user: UserSettings | None = None,
    gateway_smoke_test_time: time | None = None,
    ytdlp_auto_update: bool | None = None,
    build_feed_now: bool = False,
    train_now: bool = False,
) -> None:
    """Register all worker jobs on `scheduler` (a blocking one for the standalone
    worker, a background one when the API process runs them).

    The daily feed runs at the `feed_refresh_time` and model training at the
    `model_training_time` of the user settings (`user`, default: read now), in their time
    zone; `build_feed_now` also builds the feed right away. Channel trials are settled
    daily shortly before the feed (`TRIAL_SETTLE_LEAD`), and once at startup: that is
    cheap, and a process that was down at the usual time would otherwise leave them until
    the next day. A job re-reads the settings every `SETTINGS_CHECK_MINUTES` and
    reschedules those when they change. The live Gateway smoke test is opt-in: it runs
    daily at `gateway_smoke_test_time` (default
    `GATEWAY_SMOKE_TEST_TIME`) and isn't scheduled when neither is set. So is the
    yt-dlp update check (daily, and once shortly after startup): it needs
    `ytdlp_auto_update` (default `YTDLP_AUTO_UPDATE`).

    `build_feed_now` and `train_now` are startup catch-up: cron runs missed while the
    process was down don't fire on their own, so those jobs also run once right away (in
    the scheduler's thread pool, without blocking startup).
    """
    user = user or load_user_settings()
    smoke_time = gateway_smoke_test_time or get_settings().gateway_smoke_test_time
    triggers = daily_triggers(user, smoke_time)
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
        triggers["daily_feed"],
        id="daily_feed",
        name="Build the daily feed",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
        next_run_time=datetime.now(UTC) if build_feed_now else undefined,
    )
    scheduler.add_job(
        train,
        triggers["train_model"],
        id="train_model",
        name="Train the ranking model",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
        next_run_time=datetime.now(UTC) if train_now else undefined,
    )
    scheduler.add_job(
        settle,
        triggers["settle_trials"],
        id="settle_trials",
        name="Settle channel trials",
        next_run_time=datetime.now(UTC),  # also settles right away on startup
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
    )
    scheduler.add_job(
        pipeline.fetch_external_sources,
        IntervalTrigger(minutes=EXTERNAL_SOURCES_CHECK_MINUTES, timezone=UTC),
        id="fetch_external_sources",
        name="Fetch external sources",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
    )
    scheduler.add_job(
        pipeline.discover_tag_videos,
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
            triggers["gateway_smoke_test"],
            id="gateway_smoke_test",
            name="Live Gateway smoke test",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=None,
        )
    if get_settings().ytdlp_auto_update if ytdlp_auto_update is None else ytdlp_auto_update:
        scheduler.add_job(
            ytdlp_update,
            IntervalTrigger(hours=YTDLP_UPDATE_HOURS, timezone=UTC),
            id="update_ytdlp",
            name="Update yt-dlp",
            next_run_time=datetime.now(UTC) + timedelta(minutes=YTDLP_UPDATE_STARTUP_DELAY_MINUTES),
            max_instances=1,
            coalesce=True,
            misfire_grace_time=None,
        )
    scheduler.add_job(
        sync_schedule,
        IntervalTrigger(minutes=SETTINGS_CHECK_MINUTES, timezone=UTC),
        args=[scheduler],
        kwargs={"smoke_time": smoke_time},
        id="sync_schedule",
        name="Apply schedule changes from the settings",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=None,
    )


def build_scheduler(**kwargs: Any) -> BlockingScheduler:
    """A blocking scheduler with all worker jobs registered (see `register_jobs`)."""
    scheduler = BlockingScheduler(timezone=UTC)
    register_jobs(scheduler, **kwargs)
    return scheduler


def catch_up_needed() -> tuple[bool, bool]:
    """Whether today's feed is missing and whether training is overdue, for a process
    that has just started (a laptop is often asleep or off at FEED_REFRESH_TIME and
    MODEL_TRAINING_TIME, as the user settings have them). Returns
    `(build_feed_now, train_now)`."""
    with get_session_factory()() as session:
        user = get_user_settings(session)
        missing_today = get_feed(session, local_today(tz=user.tz)) is None
        overdue = trainer.is_training_overdue(
            session, training_time=user.model_training_time, tz=user.tz
        )
    return missing_today, overdue


def start_background_scheduler() -> BackgroundScheduler:
    """Start the worker jobs on a background thread of this process (the API's, when
    `RUN_WORKER_IN_API` is set), with startup catch-up. Stop it with `shutdown`."""
    build_feed_now, train_now = catch_up_needed()
    scheduler = BackgroundScheduler(timezone=UTC)
    register_jobs(scheduler, build_feed_now=build_feed_now, train_now=train_now)
    scheduler.start()
    logger.info("Worker jobs started in this process")
    return scheduler
