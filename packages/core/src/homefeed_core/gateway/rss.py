"""Fetching channel RSS feeds (`/feeds/videos.xml?channel_id=...`).

The poller parses and schedules feeds; this module only downloads them, so that every
request to youtube.com still goes through the Gateway package (PLAN.md ground rule 1).
"""

import time
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from http.client import HTTPResponse
from typing import Protocol

from homefeed_core.gateway.errors import (
    ExtractionError,
    GatewayError,
    RateLimitedError,
    UnavailableError,
)
from homefeed_core.gateway.events import EventRecorder, ExtractorEvent
from homefeed_core.gateway.resilience import RateLimiter
from homefeed_core.gateway.urls import CHANNEL_ID

OPERATION = "get_channel_feed"
TIMEOUT_SECONDS = 20
MAX_FEED_BYTES = 5_000_000  # a feed is ~20 KB; anything this big isn't one
_USER_AGENT = "Mozilla/5.0 (compatible; homefeed/0.1)"


def channel_feed_url(channel_id: str) -> str:
    return f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


class FeedFetcher(Protocol):
    def __call__(self, channel_id: str) -> bytes:
        """The raw RSS (Atom) XML of the channel's latest uploads.

        Raises `UnavailableError` if the channel has no feed (404), `RateLimitedError`
        when throttled and `ExtractionError` for other failures.
        """
        ...


OpenUrl = Callable[[urllib.request.Request, float], HTTPResponse]


def _urlopen(request: urllib.request.Request, timeout: float) -> HTTPResponse:
    return urllib.request.urlopen(request, timeout=timeout)


class HttpFeedFetcher:
    """`FeedFetcher` over HTTPS, rate limited, recording outcomes as extractor events.

    It doesn't retry: a failed channel is retried by the poller's per-channel backoff.
    """

    def __init__(
        self,
        *,
        recorder: EventRecorder | None = None,
        rate_limiter: RateLimiter | None = None,
        open_url: OpenUrl = _urlopen,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self._recorder = recorder
        self._rate_limiter = rate_limiter or RateLimiter()
        self._open_url = open_url
        self._timeout = timeout

    def __call__(self, channel_id: str) -> bytes:
        if not CHANNEL_ID.match(channel_id):
            raise UnavailableError(f"Not a channel id: {channel_id!r}")
        started_at = datetime.now(UTC)
        started = time.monotonic()
        try:
            self._rate_limiter.wait()
            body = self._get(channel_feed_url(channel_id))
        except GatewayError as error:
            self._record(channel_id, started_at, started, error)
            raise
        self._record(channel_id, started_at, started, None)
        return body

    def _get(self, url: str) -> bytes:
        request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        try:
            with self._open_url(request, self._timeout) as response:
                body = response.read(MAX_FEED_BYTES + 1)
        except urllib.error.HTTPError as error:
            raise _http_error(error.code, url) from error
        except (urllib.error.URLError, OSError) as error:
            raise ExtractionError(f"Could not fetch {url}: {error}") from error
        if len(body) > MAX_FEED_BYTES:
            raise ExtractionError(f"Feed at {url} is larger than {MAX_FEED_BYTES} bytes")
        return body

    def _record(
        self, channel_id: str, at: datetime, started: float, error: GatewayError | None
    ) -> None:
        if self._recorder is None:
            return
        self._recorder.record(
            ExtractorEvent(
                operation=OPERATION,
                target=channel_id,
                success=error is None,
                at=at,
                duration_ms=round((time.monotonic() - started) * 1000),
                error_kind=error.kind if error else None,
                error=str(error) if error else None,
            )
        )


def _http_error(status: int, url: str) -> GatewayError:
    message = f"HTTP Error {status} fetching {url}"
    if status in (404, 410):
        return UnavailableError(message)
    if status == 429:
        return RateLimitedError(message)
    return ExtractionError(message)
