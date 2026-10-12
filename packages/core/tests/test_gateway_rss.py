import io
import urllib.error
import urllib.request
from http.client import HTTPResponse
from typing import cast

import pytest

from homefeed_core.gateway import (
    ExtractionError,
    GatewayError,
    HttpFeedFetcher,
    MemoryEventRecorder,
    RateLimitedError,
    RateLimiter,
    UnavailableError,
    channel_feed_url,
)

CHANNEL = "UC4QobU6STFB0P71PMvOGN5A"
URL = "https://www.youtube.com/feeds/videos.xml?channel_id=UC4QobU6STFB0P71PMvOGN5A"


class Response(io.BytesIO):
    pass


def fetcher(
    respond: bytes | Exception, recorder: MemoryEventRecorder
) -> tuple[HttpFeedFetcher, list[str]]:
    requested: list[str] = []

    def open_url(request: urllib.request.Request, timeout: float) -> HTTPResponse:
        requested.append(request.full_url)
        if isinstance(respond, Exception):
            raise respond
        return cast(HTTPResponse, Response(respond))

    limiter = RateLimiter(0.0, sleep=lambda _: None)
    return HttpFeedFetcher(recorder=recorder, rate_limiter=limiter, open_url=open_url), requested


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(URL, code, "error", {}, None)  # pyright: ignore[reportArgumentType]


def test_feed_url() -> None:
    assert channel_feed_url(CHANNEL) == URL


def test_fetch_returns_body_and_records_success() -> None:
    recorder = MemoryEventRecorder()
    fetch, requested = fetcher(b"<feed/>", recorder)

    assert fetch(CHANNEL) == b"<feed/>"
    assert requested == [URL]
    [event] = recorder.events
    assert (event.operation, event.target, event.success) == ("get_channel_feed", CHANNEL, True)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (http_error(404), UnavailableError),
        (http_error(429), RateLimitedError),
        (http_error(500), ExtractionError),
        (urllib.error.URLError("timed out"), ExtractionError),
        (TimeoutError("timed out"), ExtractionError),
    ],
)
def test_fetch_errors_become_gateway_errors(error: Exception, expected: type[GatewayError]) -> None:
    recorder = MemoryEventRecorder()
    fetch, _ = fetcher(error, recorder)

    with pytest.raises(expected):
        fetch(CHANNEL)
    [event] = recorder.events
    assert event.success is False
    assert event.error_kind == expected.kind


def test_fetch_rejects_bad_channel_ids_without_a_request() -> None:
    recorder = MemoryEventRecorder()
    fetch, requested = fetcher(b"", recorder)

    with pytest.raises(UnavailableError):
        fetch("not-a-channel")
    assert requested == []
