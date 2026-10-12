from datetime import time, timedelta
from typing import Any

from apscheduler.job import Job
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from homefeed_worker.scheduler import (
    POLL_CHECK_MINUTES,
    build_daily_feed,
    build_scheduler,
    poll_subscriptions,
)


def jobs_by_id(**kwargs: Any) -> dict[str, Job]:
    scheduler = build_scheduler(**kwargs)
    assert not scheduler.running
    return {job.id: job for job in scheduler.get_jobs()}


def test_build_scheduler_registers_the_subscription_poll() -> None:
    job = jobs_by_id()["poll_subscriptions"]

    assert job.func is poll_subscriptions
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval == timedelta(minutes=POLL_CHECK_MINUTES)
    assert job.max_instances == 1
    assert job.coalesce is True


def test_build_scheduler_registers_the_daily_feed_at_refresh_time() -> None:
    job = jobs_by_id(feed_refresh_time=time(7, 30))["daily_feed"]

    assert job.func is build_daily_feed
    assert isinstance(job.trigger, CronTrigger)
    fields = {field.name: str(field) for field in job.trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("7", "30")
    assert job.max_instances == 1
    assert job.coalesce is True


def test_daily_feed_waits_for_refresh_time_unless_asked_to_build_now() -> None:
    later = jobs_by_id(feed_refresh_time=time(6, 0))["daily_feed"]
    now = jobs_by_id(feed_refresh_time=time(6, 0), build_feed_now=True)["daily_feed"]

    # Not started, so jobs without an explicit next run time have none yet.
    assert not hasattr(later, "next_run_time") or later.next_run_time is None
    assert now.next_run_time is not None


def test_jobs_run_the_given_functions() -> None:
    calls: list[str] = []
    jobs = jobs_by_id(poll=lambda: calls.append("poll"), build_feed=lambda: calls.append("feed"))

    jobs["poll_subscriptions"].func()
    jobs["daily_feed"].func()

    assert calls == ["poll", "feed"]
