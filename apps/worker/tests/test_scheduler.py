from collections.abc import Callable, Iterator
from datetime import time, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from apscheduler.job import Job
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from homefeed_core.config import get_settings
from homefeed_worker import scheduler
from homefeed_worker.scheduler import (
    ENRICH_CHECK_MINUTES,
    POLL_CHECK_MINUTES,
    build_daily_feed,
    build_scheduler,
    enrich_candidates,
    gather_candidates,
    poll_subscriptions,
    run_gateway_smoke_test,
    train_model,
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


def test_build_scheduler_registers_candidate_enrichment() -> None:
    job = jobs_by_id()["enrich_candidates"]

    assert job.func is enrich_candidates
    assert isinstance(job.trigger, IntervalTrigger)
    assert job.trigger.interval == timedelta(minutes=ENRICH_CHECK_MINUTES)
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


def test_build_scheduler_registers_nightly_training_at_training_time() -> None:
    job = jobs_by_id(model_training_time=time(2, 45))["train_model"]

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
    later = jobs_by_id(feed_refresh_time=time(6, 0))["daily_feed"]
    now = jobs_by_id(feed_refresh_time=time(6, 0), build_feed_now=True)["daily_feed"]

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
