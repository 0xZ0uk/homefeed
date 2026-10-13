"""Gateway `search`, against recorded responses (see test_gateway.py for the harness)."""

import base64
from datetime import UTC, datetime

import pytest
from gateway_fixtures import Replay

from homefeed_core.gateway import (
    MemoryEventRecorder,
    RateLimiter,
    RetryPolicy,
    SearchFilters,
    UnavailableError,
    YtDlpGateway,
)
from homefeed_core.gateway.fake import FakeGateway, make_channel, make_video
from homefeed_core.gateway.normalize import search_results_from_info
from homefeed_core.gateway.ytdlp import ExtractRequest, search_params, search_url

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
FILTERS = SearchFilters(sort="upload_date", upload_date="month", duration="long")


@pytest.fixture
def replay() -> Replay:
    return Replay()


@pytest.fixture
def recorder() -> MemoryEventRecorder:
    return MemoryEventRecorder()


@pytest.fixture
def gateway(replay: Replay, recorder: MemoryEventRecorder) -> YtDlpGateway:
    return YtDlpGateway(
        recorder=recorder,
        retry=RetryPolicy(attempts=3, initial_delay=1.0, multiplier=2.0, jitter=0.0),
        rate_limiter=RateLimiter(0.0),
        extract=replay,
        sleep=lambda _seconds: None,
        now=lambda: NOW,
    )


def test_search_uses_ytsearch(
    gateway: YtDlpGateway, replay: Replay, recorder: MemoryEventRecorder
) -> None:
    results = gateway.search("  woodworking   hand planes ", limit=5)

    assert replay.requests == [
        ExtractRequest("ytsearch5:woodworking hand planes", flat=True, limit=5)
    ]
    assert [result.id for result in results] == [
        "v0VItLJTRnU",
        "xqA9BL3CJU0",
        "z6FlNGYiY7A",
        "ODpVgpxXOEY",
        "YUjSBAq6iGg",
    ]
    second = results[1]
    assert (second.title, second.channel_id, second.channel_title, second.channel_handle) == (
        "Hand Planes For Woodworking - Types & Sizes",
        "UCK9d9JGoPgPGXX8oVxCxjcg",
        "The English Woodworker",
        "@TheEnglishWoodworker",
    )
    assert (second.duration_seconds, second.view_count, second.live_status) == (
        922,
        113392,
        None,
    )
    assert second.description and second.description.startswith("Bench planes")
    assert second.thumbnail_url and "xqA9BL3CJU0" in second.thumbnail_url
    [event] = recorder.events
    assert (event.operation, event.target, event.success) == (
        "search",
        "woodworking hand planes",
        True,
    )


def test_search_with_filters_uses_the_results_page(gateway: YtDlpGateway, replay: Replay) -> None:
    results = gateway.search("woodworking", FILTERS, limit=5)

    [request] = replay.requests
    assert request.url == (
        "https://www.youtube.com/results?search_query=woodworking&sp=CAISBggEEAEYAg%3D%3D"
    )
    assert len(results) == 5
    # "Long" means over 20 minutes.
    assert all((result.duration_seconds or 0) > 20 * 60 for result in results)


def test_search_with_default_filters_is_a_plain_search(
    gateway: YtDlpGateway, replay: Replay
) -> None:
    gateway.search("woodworking hand planes", SearchFilters(), limit=5)

    assert replay.requests[0].url == "ytsearch5:woodworking hand planes"


def test_search_without_results(gateway: YtDlpGateway) -> None:
    assert gateway.search("qxzvbnmplkjh wrtpsdfgh zzqqxx", limit=5) == []


def test_search_limit_trims_results(gateway: YtDlpGateway, replay: Replay) -> None:
    replay.records[ExtractRequest("ytsearch2:woodworking hand planes", flat=True, limit=2)] = (
        replay.records[ExtractRequest("ytsearch5:woodworking hand planes", flat=True, limit=5)]
    )

    results = gateway.search("woodworking hand planes", limit=2)

    assert [result.id for result in results] == ["v0VItLJTRnU", "xqA9BL3CJU0"]


@pytest.mark.parametrize("query", ["", "   ", "x" * 201])
def test_search_rejects_blank_and_long_queries(
    gateway: YtDlpGateway, replay: Replay, query: str
) -> None:
    with pytest.raises(ValueError):
        gateway.search(query)
    assert replay.requests == []


@pytest.mark.parametrize("limit", [0, 51])
def test_search_rejects_bad_limits(gateway: YtDlpGateway, replay: Replay, limit: int) -> None:
    with pytest.raises(ValueError):
        gateway.search("woodworking", limit=limit)
    assert replay.requests == []


def test_search_records_failures(recorder: MemoryEventRecorder) -> None:
    def refuse(_request: ExtractRequest) -> dict[str, object]:
        raise UnavailableError("HTTP Error 404: Not Found")

    gateway = YtDlpGateway(
        recorder=recorder,
        retry=RetryPolicy(attempts=1),
        rate_limiter=RateLimiter(0.0),
        extract=refuse,
        now=lambda: NOW,
    )

    with pytest.raises(UnavailableError):
        gateway.search("woodworking")

    [event] = recorder.events
    assert (event.operation, event.target, event.success, event.error_kind) == (
        "search",
        "woodworking",
        False,
        "unavailable",
    )


def decode(params: str) -> bytes:
    return base64.b64decode(params)


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        # Videos only.
        (SearchFilters(), bytes([0x12, 0x02, 0x10, 0x01])),
        # Newest first, uploaded this month (what yt-dlp's `ytsearchdate` sends, plus a date).
        (
            SearchFilters(sort="upload_date", upload_date="month"),
            bytes([0x08, 0x02, 0x12, 0x04, 0x08, 0x04, 0x10, 0x01]),
        ),
        (
            SearchFilters(sort="view_count", duration="short"),
            bytes([0x08, 0x03, 0x12, 0x04, 0x10, 0x01, 0x18, 0x01]),
        ),
        (
            SearchFilters(upload_date="today", duration="medium"),
            bytes([0x12, 0x06, 0x08, 0x02, 0x10, 0x01, 0x18, 0x03]),
        ),
    ],
)
def test_search_params(filters: SearchFilters, expected: bytes) -> None:
    assert decode(search_params(filters)) == expected


def test_search_url_escapes_the_query() -> None:
    assert search_url("rock & roll", None, 10) == "ytsearch10:rock & roll"
    assert search_url("rock & roll", SearchFilters(sort="rating"), 10) == (
        "https://www.youtube.com/results?search_query=rock%20%26%20roll&sp=CAESAhAB"
    )


def test_search_results_from_info_skips_duplicates_and_incomplete_entries() -> None:
    channel = "UC" + "v" * 22
    entry = {"id": "aaaaaaaaaaa", "title": "A", "channel_id": channel, "channel": "V"}

    results = search_results_from_info(
        {
            "id": "query",
            "entries": [
                entry,
                entry,
                {**entry, "id": "bbbbbbbbbbb", "channel_id": None},
                {**entry, "id": "ccccccccccc", "title": None},
                {**entry, "id": "UCxxxxxxxxxxxxxxxxxxxxxx"},  # a channel result
                "junk",
                {**entry, "id": "ddddddddddd", "live_status": "is_upcoming"},
            ],
        }
    )

    assert [(result.id, result.live_status) for result in results] == [
        ("aaaaaaaaaaa", None),
        ("ddddddddddd", "is_upcoming"),
    ]


def test_fake_gateway_search() -> None:
    gateway = FakeGateway()
    channel = make_channel("UC" + "w" * 22, title="Wood", handle="@wood")
    gateway.add_search("Hand  planes", [make_video(f"{c}" * 11, channel=channel) for c in "abc"])

    results = gateway.search("hand planes", FILTERS, limit=2)

    assert results == []  # queries match exactly, after whitespace is collapsed
    results = gateway.search(" Hand planes ", FILTERS, limit=2)
    assert [result.id for result in results] == ["a" * 11, "b" * 11]
    assert results[0].channel_handle == "@wood"
    assert gateway.searches[-1] == ("Hand planes", FILTERS)
    assert gateway.get_video("c" * 11).channel_id == channel.id
