from collections.abc import Callable, Iterator
from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from apscheduler.job import Job
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.base import BaseScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from homefeed_core.config import Settings, get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.user_settings import UserSettings, default_user_settings, update_user_settings
from homefeed_worker import scheduler
from homefeed_worker.scheduler import (
    ENRICH_CHECK_MINUTES,
    POLL_CHECK_MINUTES,
    build_daily_feed,
    build_scheduler,
    enrich_candidates,
    gather_candidates,
    poll_subscriptions,
    register_jobs,
    run_gateway_smoke_test,
    train_model,
)


def user(**changes: Any) -> UserSettings:
    return default_user_settings(Settings()).model_copy(update=changes)


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


def test_build_scheduler_registers_candidate_enrichment() -> None:
    job = jobs_by_id()["enrich_candidates"]

    assert job.func is enrich_candidates
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval == timedelta(minutes=ENRICH_CHECK_MINUTES)
    assert job.max_instances == 1
    assert job.coalesce is True


def test_build_scheduler_registers_the_daily_feed_at_refresh_time() -> None:
    job = jobs_by_id(user=user(feed_refresh_time=time(7, 30)))["daily_feed"]

    assert job.func is build_daily_feed
    assert isinstance(job.trigger, CronTrigger)
    fields = {field.name: str(field) for field in job.trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("7", "30")
    assert job.max_instances == 1
    assert job.coalesce is True


def test_build_scheduler_registers_nightly_training_at_training_time() -> None:
    job = jobs_by_id(user=user(model_training_time=time(2, 45)))["train_model"]

    assert job.func is train_model
    assert isinstance(job.trigger, CronTrigger)
    fields = {field.name: str(field) for field in job.trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("2", "45")
    assert job.max_instances == 1
    assert job.coalesce is True


def test_training_runs_the_nightly_trainer(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(scheduler.trainer, "run_nightly_training", lambda: calls.append("train"))

    train_model()

    assert calls == ["train"]


def test_daily_feed_waits_for_refresh_time_unless_asked_to_build_now() -> None:
    later = jobs_by_id(user=user(feed_refresh_time=time(6, 0)))["daily_feed"]
    now = jobs_by_id(user=user(feed_refresh_time=time(6, 0)), build_feed_now=True)["daily_feed"]

    # Not started, so jobs without an explicit next run time have none yet.
    assert not hasattr(later, "next_run_time") or later.next_run_time is None
    assert now.next_run_time is not None


def test_jobs_run_the_given_functions() -> None:
    calls: list[str] = []
    jobs = jobs_by_id(
        poll=lambda: calls.append("poll"),
        enrich=lambda: calls.append("enrich"),
        build_feed=lambda: calls.append("feed"),
        train=lambda: calls.append("train"),
    )

    jobs["poll_subscriptions"].func()
    jobs["enrich_candidates"].func()
    jobs["daily_feed"].func()
    jobs["train_model"].func()

    assert calls == ["poll", "enrich", "feed", "train"]


def test_daily_feed_gathers_and_enriches_before_ranking(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, Any] = {}

    def refresh_feed(**kwargs: Any) -> Any:
        received.update(kwargs)
        return SimpleNamespace(date="2026-10-12", items=[])

    monkeypatch.setattr(scheduler.feeds, "refresh_feed", refresh_feed)

    build_daily_feed()

    assert received == {"poll": gather_candidates, "enrich": enrich_candidates}


def test_gathering_runs_the_other_sources_even_if_polling_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def failing_poll() -> list[str]:
        calls.append("poll")
        raise RuntimeError("database locked")

    def generate() -> SimpleNamespace:
        calls.append("generate")
        return SimpleNamespace(new={"related": ["aaaaaaaaaaa"]}, failed={"other": "boom"})

    monkeypatch.setattr(scheduler.poller, "poll_due_channels", failing_poll)
    monkeypatch.setattr(scheduler.candidates, "generate", generate)

    gather_candidates()

    assert calls == ["poll", "generate"]


def test_build_scheduler_registers_the_external_sources_check() -> None:
    job = jobs_by_id()["fetch_external_sources"]

    assert job.func is scheduler.fetch_external_sources
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval == timedelta(minutes=scheduler.EXTERNAL_SOURCES_CHECK_MINUTES)
    assert job.max_instances == 1
    assert job.coalesce is True


def test_external_sources_job_runs_only_that_source(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[list[str]] = []

    def generate(sources: list[Any], **_kwargs: Any) -> SimpleNamespace:
        ran.append([source.name for source in sources])
        return SimpleNamespace(new={"external": ["aaaaaaaaaaa"]}, failed={})

    monkeypatch.setattr(scheduler, "get_session_factory", lambda: None)
    monkeypatch.setattr(scheduler, "create_gateway", lambda _sessions: None)
    monkeypatch.setattr(scheduler.candidates, "generate", generate)

    scheduler.fetch_external_sources()

    assert ran == [["external"]]


@pytest.fixture
def smoke_test_setting(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[str | None], None]]:
    """Set (or unset) GATEWAY_SMOKE_TEST_TIME for `build_scheduler`."""

    def set_time(value: str | None) -> None:
        if value is None:
            monkeypatch.delenv("GATEWAY_SMOKE_TEST_TIME", raising=False)
        else:
            monkeypatch.setenv("GATEWAY_SMOKE_TEST_TIME", value)
        get_settings.cache_clear()

    yield set_time
    get_settings.cache_clear()


def test_live_smoke_test_is_not_scheduled_by_default(
    smoke_test_setting: Callable[[str | None], None],
) -> None:
    smoke_test_setting(None)

    assert "gateway_smoke_test" not in jobs_by_id()


def test_live_smoke_test_is_scheduled_when_configured(
    smoke_test_setting: Callable[[str | None], None],
) -> None:
    smoke_test_setting("05:30")

    job = jobs_by_id()["gateway_smoke_test"]

    assert job.func is run_gateway_smoke_test
    assert isinstance(job.trigger, CronTrigger)
    fields = {field.name: str(field) for field in job.trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("5", "30")
    assert job.max_instances == 1
    assert job.coalesce is True


def test_live_smoke_test_time_can_be_given(
    smoke_test_setting: Callable[[str | None], None],
) -> None:
    smoke_test_setting(None)
    calls: list[str] = []

    job = jobs_by_id(smoke=lambda: calls.append("smoke"), gateway_smoke_test_time=time(4, 15))[
        "gateway_smoke_test"
    ]
    job.func()

    fields = {field.name: str(field) for field in job.trigger.fields}
    assert (fields["hour"], fields["minute"]) == ("4", "15")
    assert calls == ["smoke"]


@pytest.mark.parametrize("success", [True, False])
def test_smoke_test_job_logs_the_outcome(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, success: bool
) -> None:
    report = SimpleNamespace(success=success, checks=[1, 2], summary=lambda: "get_video: boom")
    monkeypatch.setattr(scheduler.smoke_test, "run_live_smoke_test", lambda: report)

    with caplog.at_level("INFO"):
        run_gateway_smoke_test()

    expected = "Gateway smoke test passed" if success else "get_video: boom"
    assert expected in caplog.text


def test_build_scheduler_registers_the_tag_discovery_check() -> None:
    job = jobs_by_id()["discover_tag_videos"]

    assert job.func is scheduler.discover_tag_videos
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval == timedelta(minutes=scheduler.TAG_DISCOVERY_CHECK_MINUTES)
    assert job.max_instances == 1
    assert job.coalesce is True


def test_tag_discovery_job_runs_only_that_source(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[list[str]] = []

    def generate(sources: list[Any], **_kwargs: Any) -> SimpleNamespace:
        ran.append([source.name for source in sources])
        return SimpleNamespace(new={"tag": ["aaaaaaaaaaa"]}, failed={})

    monkeypatch.setattr(scheduler, "get_session_factory", lambda: None)
    monkeypatch.setattr(scheduler, "create_gateway", lambda _sessions: None)
    monkeypatch.setattr(scheduler.candidates, "generate", generate)

    scheduler.discover_tag_videos()

    assert ran == [["tag"]]


def test_register_jobs_works_on_a_background_scheduler() -> None:
    background = BackgroundScheduler(timezone=UTC)

    register_jobs(background)

    assert not background.running
    assert {job.id for job in background.get_jobs()} == {
        job.id for job in build_scheduler().get_jobs()
    }


def test_build_scheduler_is_blocking() -> None:
    assert isinstance(build_scheduler(), BlockingScheduler)


def test_training_runs_at_startup_only_when_asked() -> None:
    now = datetime.now(UTC)
    job = jobs_by_id(train_now=True)["train_model"]

    assert job.next_run_time is not None
    assert abs(job.next_run_time - now) < timedelta(seconds=5)
    assert isinstance(job.trigger, CronTrigger)  # the nightly schedule stays


def test_start_background_scheduler_starts_with_catch_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(scheduler, "catch_up_needed", lambda: (True, True))
    # Stand-in jobs: the real ones would poll, enrich, build a feed and train right away,
    # on threads that outlive the test (and its throwaway database).
    calls: list[str] = []
    real_register_jobs = register_jobs

    def register(background: BaseScheduler, **kwargs: Any) -> None:
        real_register_jobs(
            background,
            poll=lambda: calls.append("poll"),
            enrich=lambda: calls.append("enrich"),
            build_feed=lambda: calls.append("feed"),
            train=lambda: calls.append("train"),
            **kwargs,
        )

    monkeypatch.setattr(scheduler, "register_jobs", register)
    started = scheduler.start_background_scheduler()
    try:
        assert started.running
        assert isinstance(started, BackgroundScheduler)
    finally:
        started.shutdown(wait=True)
    assert not started.running


# User settings: times, time zone, live rescheduling


def cron_at(job: Job) -> tuple[str, str, str]:
    assert isinstance(job.trigger, CronTrigger)
    fields = {field.name: str(field) for field in job.trigger.fields}
    return fields["hour"], fields["minute"], str(job.trigger.timezone)


def store(**changes: Any) -> None:
    with get_session_factory().begin() as session:
        update_user_settings(session, changes)


def run_job(background: BackgroundScheduler, job_id: str) -> None:
    job = background.get_job(job_id)
    assert job is not None
    job.func(*job.args, **job.kwargs)


def test_daily_jobs_follow_the_stored_user_settings() -> None:
    store(feed_refresh_time=time(8, 15), model_training_time=time(1, 5), timezone="Asia/Tokyo")

    jobs = jobs_by_id()

    assert cron_at(jobs["daily_feed"]) == ("8", "15", "Asia/Tokyo")
    assert cron_at(jobs["train_model"]) == ("1", "5", "Asia/Tokyo")


def test_smoke_test_runs_in_the_user_time_zone(
    smoke_test_setting: Callable[[str | None], None],
) -> None:
    smoke_test_setting("05:30")

    job = jobs_by_id(user=user(timezone="America/Sao_Paulo"))["gateway_smoke_test"]

    assert cron_at(job) == ("5", "30", "America/Sao_Paulo")


def test_settings_check_is_registered() -> None:
    job = jobs_by_id()["sync_schedule"]

    assert job.func is scheduler.sync_schedule
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval == timedelta(minutes=scheduler.SETTINGS_CHECK_MINUTES)
    assert job.max_instances == 1


def test_settings_check_reschedules_changed_times_and_time_zone() -> None:
    background = BackgroundScheduler(timezone=UTC)
    register_jobs(background, user=user(feed_refresh_time=time(6, 0)))
    background.start(paused=True)
    try:
        store(feed_refresh_time=time(9, 45), timezone="Europe/Lisbon")

        run_job(background, "sync_schedule")

        feed = background.get_job("daily_feed")
        assert feed is not None
        assert cron_at(feed) == ("9", "45", "Europe/Lisbon")
        local = feed.next_run_time.astimezone(ZoneInfo("Europe/Lisbon"))
        assert (local.hour, local.minute) == (9, 45)
        training = background.get_job("train_model")
        assert training is not None
        assert cron_at(training)[2] == "Europe/Lisbon"  # the time zone moves every daily job
        local = training.next_run_time.astimezone(ZoneInfo("Europe/Lisbon"))
        assert (local.hour, local.minute) == (3, 0)
    finally:
        background.shutdown(wait=False)


def test_settings_check_leaves_unchanged_jobs_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    background = BackgroundScheduler(timezone=UTC)
    current = user(timezone="Asia/Tokyo")
    register_jobs(background, user=current)
    rescheduled: list[str] = []
    monkeypatch.setattr(
        background, "reschedule_job", lambda job_id, **_kwargs: rescheduled.append(job_id)
    )

    scheduler.sync_schedule(background, smoke_time=None, user=current)

    assert rescheduled == []


def test_catch_up_uses_the_user_training_time_and_time_zone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store(model_training_time=time(4, 20), timezone="Pacific/Auckland")
    received: dict[str, Any] = {}

    def overdue(_session: Any, **kwargs: Any) -> bool:
        received.update(kwargs)
        return True

    monkeypatch.setattr(scheduler.trainer, "is_training_overdue", overdue)

    assert scheduler.catch_up_needed() == (True, True)  # no feed yet either
    assert received == {"training_time": time(4, 20), "tz": ZoneInfo("Pacific/Auckland")}


def test_ytdlp_update_is_not_scheduled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YTDLP_AUTO_UPDATE", raising=False)
    get_settings.cache_clear()

    assert "update_ytdlp" not in jobs_by_id()


def test_ytdlp_update_is_scheduled_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YTDLP_AUTO_UPDATE", "true")
    get_settings.cache_clear()
    try:
        job = jobs_by_id()["update_ytdlp"]
    finally:
        get_settings.cache_clear()

    assert job.func is scheduler.update_ytdlp
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval == timedelta(hours=scheduler.YTDLP_UPDATE_HOURS)
    assert job.next_run_time is not None  # also once shortly after startup


def test_ytdlp_update_job_logs_failures_instead_of_raising(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing() -> str:
        raise scheduler.ytdlp_updates.YtDlpUpdateError("offline")

    monkeypatch.setattr(scheduler.ytdlp_updates, "update", failing)

    scheduler.update_ytdlp()
