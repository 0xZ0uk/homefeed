from datetime import UTC, datetime

import pytest
from gateway_fixtures import LIVE_TESTS

from homefeed_core import smoke_test
from homefeed_core.extractor_status import SMOKE_TEST_OPERATION
from homefeed_core.gateway import (
    Captions,
    CaptionSegment,
    ExtractionError,
    HttpFeedFetcher,
    MemoryEventRecorder,
    RateLimiter,
    ResolvedChannel,
    RetryPolicy,
    UnavailableError,
    YtDlpGateway,
)
from homefeed_core.gateway.fake import (
    FakeGateway,
    make_channel,
    make_comment,
    make_format,
    make_video,
)
from homefeed_core.smoke_test import (
    VERITASIUM,
    VERITASIUM_URL,
    ZOO_TITLE,
    ZOO_VIDEO,
    run_smoke_test,
)

NOW = datetime(2026, 10, 13, 5, 30, tzinfo=UTC)
FEED = b'<feed xmlns:yt="x"><entry><yt:videoId>aaaaaaaaaaa</yt:videoId></entry></feed>'


def healthy_gateway() -> FakeGateway:
    """A fake YouTube where everything the smoke test asks for looks right."""
    gateway = FakeGateway()
    channel = make_channel(VERITASIUM, title="Veritasium", handle="@veritasium")
    zoo = make_video(ZOO_VIDEO, title=ZOO_TITLE, duration_seconds=19)
    other = make_video("bbbbbbbbbbb", channel=channel)
    gateway.add_video(
        zoo, [make_format("140"), make_format("137", kind="video", mime_type="video/mp4")]
    )
    gateway.add_captions(
        Captions(
            ZOO_VIDEO, "en", False, (CaptionSegment(0, 5, "the cool thing about these elephants"),)
        )
    )
    gateway.add_related(ZOO_VIDEO, [other])
    gateway.add_comments(ZOO_VIDEO, [make_comment()])
    gateway.add_search(smoke_test.SEARCH_QUERY, [other])
    gateway.add_channel(channel, [other])
    gateway.add_featured(VERITASIUM, [make_channel("UC" + "b" * 22, title="Other")])
    gateway.add_url(VERITASIUM_URL, ResolvedChannel(channel))
    return gateway


def test_a_healthy_gateway_passes_and_is_recorded() -> None:
    recorder = MemoryEventRecorder()

    report = run_smoke_test(
        healthy_gateway(), lambda channel_id: FEED, recorder=recorder, now=lambda: NOW
    )

    assert report.success
    assert report.summary() is None
    assert [check.name for check in report.checks] == [
        "get_video",
        "get_formats",
        "get_captions",
        "get_related",
        "get_comments",
        "search",
        "get_channel_uploads",
        "get_featured_channels",
        "resolve_url",
        "get_channel_feed",
    ]
    [event] = recorder.events
    assert (event.operation, event.success, event.at, event.error) == (
        SMOKE_TEST_OPERATION,
        True,
        NOW,
        None,
    )


def test_failing_checks_do_not_stop_the_others() -> None:
    gateway = healthy_gateway()
    gateway.fail("get_related", ZOO_VIDEO, ExtractionError("signature extraction failed"))
    gateway.videos[ZOO_VIDEO] = make_video(ZOO_VIDEO, title="Something else", duration_seconds=19)
    recorder = MemoryEventRecorder()

    report = run_smoke_test(gateway, recorder=recorder)

    assert not report.success
    failed = {check.name: (check.error_kind, check.error) for check in report.failed}
    assert failed == {
        "get_video": ("unexpected_response", "unexpected title 'Something else'"),
        "get_related": ("extraction", "signature extraction failed"),
    }
    assert len(report.checks) == len(smoke_test.GATEWAY_CHECKS)  # no feed fetcher given
    [event] = recorder.events
    assert event.success is False
    assert event.error_kind == "unexpected_response"
    assert event.error == (
        "get_video: unexpected title 'Something else'; get_related: signature extraction failed"
    )


def test_unexpected_exceptions_are_failures_too() -> None:
    def broken_feed(channel_id: str) -> bytes:
        raise KeyError("entries")

    report = run_smoke_test(healthy_gateway(), broken_feed)

    [check] = report.failed
    assert (check.name, check.error_kind) == ("get_channel_feed", "unexpected_error")


def test_missing_content_fails() -> None:
    gateway = FakeGateway()  # knows nothing: every lookup is unavailable or empty

    report = run_smoke_test(gateway, lambda channel_id: b"<html></html>")

    assert not any(check.ok for check in report.checks)
    assert report.failed[0].error_kind == UnavailableError.kind


@pytest.mark.skipif(LIVE_TESTS, reason="needs the network to be blocked")
def test_real_gateway_without_network_fails_every_check() -> None:
    """With the network blocked, the real Gateway fails each check instead of raising."""
    gateway = YtDlpGateway(retry=RetryPolicy(attempts=1), rate_limiter=RateLimiter(0.0))

    report = run_smoke_test(gateway, HttpFeedFetcher(rate_limiter=RateLimiter(0.0)))

    assert report.checks and not any(check.ok for check in report.checks)


@pytest.mark.skipif(not LIVE_TESTS, reason="live smoke test; set HOMEFEED_LIVE_TESTS=1")
def test_live_smoke_test_passes() -> None:
    report = run_smoke_test(
        YtDlpGateway(rate_limiter=RateLimiter(1.0)), HttpFeedFetcher(), recorder=None
    )

    assert report.success, report.summary()
