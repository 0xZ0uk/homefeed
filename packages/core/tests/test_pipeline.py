"""The candidate pipeline's behaviour: run order, failure isolation, and its locks.

The jobs layer (see test_jobs.py) only schedules these; what runs in what order is
tested here, with the poller, sources and feed build replaced by stubs.
"""

from types import SimpleNamespace
from typing import Any

import pytest

from homefeed_core import pipeline


def test_gathering_polls_then_runs_the_other_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def poll(**_kwargs: Any) -> list[str]:
        calls.append("poll")
        return []

    monkeypatch.setattr(pipeline.poller, "poll_due_channels", poll)

    def generate(**_kwargs: Any) -> SimpleNamespace:
        calls.append("generate")
        return SimpleNamespace(new={}, failed={})

    monkeypatch.setattr(pipeline.candidates, "generate", generate)

    pipeline.gather_candidates()

    assert calls == ["poll", "generate"]


def test_gathering_runs_the_other_sources_even_if_polling_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def failing_poll(**_kwargs: Any) -> list[str]:
        calls.append("poll")
        raise RuntimeError("database locked")

    def generate(**_kwargs: Any) -> SimpleNamespace:
        calls.append("generate")
        return SimpleNamespace(new={"related": ["aaaaaaaaaaa"]}, failed={"other": "boom"})

    monkeypatch.setattr(pipeline.poller, "poll_due_channels", failing_poll)
    monkeypatch.setattr(pipeline.candidates, "generate", generate)

    pipeline.gather_candidates()

    assert calls == ["poll", "generate"]


def test_daily_feed_gathers_and_enriches_before_ranking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, Any] = {}

    def refresh_feed(**kwargs: Any) -> Any:
        received.update(kwargs)
        return SimpleNamespace(date="2026-10-12", items=[])

    monkeypatch.setattr(pipeline.feeds, "refresh_feed", refresh_feed)

    pipeline.build_daily_feed()

    assert received == {
        "poll": pipeline.gather_candidates,
        "enrich": pipeline.enrich_candidates,
    }


def test_poll_passes_the_given_fetcher_to_the_poller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, Any] = {}

    def poll(**kwargs: Any) -> list[str]:
        received.update(kwargs)
        return ["aaaaaaaaaaa"]

    monkeypatch.setattr(pipeline.poller, "poll_due_channels", poll)
    fetcher = lambda _channel_id: b"<feed/>"  # noqa: E731 - a stand-in FeedFetcher

    pipeline.poll_subscriptions(fetch=fetcher)  # type: ignore[arg-type]

    assert received == {"fetch": fetcher}


def test_polling_holds_the_poll_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    held: list[bool] = []

    def poll(**_kwargs: Any) -> list[str]:
        held.append(pipeline._poll_lock.locked())
        return []

    monkeypatch.setattr(pipeline.poller, "poll_due_channels", poll)

    pipeline.poll_subscriptions()

    assert held == [True]
    assert not pipeline._poll_lock.locked()


def test_enriching_holds_the_enrich_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    held: list[bool] = []

    def enrich(**_kwargs: Any) -> SimpleNamespace:
        held.append(pipeline._enrich_lock.locked())
        return SimpleNamespace(enriched=[], cached=[], failed=[])

    monkeypatch.setattr(pipeline.enricher, "enrich_candidates", enrich)

    pipeline.enrich_candidates()

    assert held == [True]
    assert not pipeline._enrich_lock.locked()


def test_external_sources_job_runs_only_that_source(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[list[str]] = []

    def generate(sources: list[Any], **_kwargs: Any) -> SimpleNamespace:
        ran.append([source.name for source in sources])
        return SimpleNamespace(new={"external": ["aaaaaaaaaaa"]}, failed={})

    monkeypatch.setattr(pipeline, "get_session_factory", lambda: None)
    monkeypatch.setattr(pipeline, "create_gateway", lambda _sessions: None)
    monkeypatch.setattr(pipeline.candidates, "generate", generate)

    pipeline.fetch_external_sources()

    assert ran == [["external"]]


def test_tag_discovery_job_runs_only_that_source(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[list[str]] = []

    def generate(sources: list[Any], **_kwargs: Any) -> SimpleNamespace:
        ran.append([source.name for source in sources])
        return SimpleNamespace(new={"tag": ["aaaaaaaaaaa"]}, failed={})

    monkeypatch.setattr(pipeline, "get_session_factory", lambda: None)
    monkeypatch.setattr(pipeline, "create_gateway", lambda _sessions: None)
    monkeypatch.setattr(pipeline.candidates, "generate", generate)

    pipeline.discover_tag_videos()

    assert ran == [["tag"]]
