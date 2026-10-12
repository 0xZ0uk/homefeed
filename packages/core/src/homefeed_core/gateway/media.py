"""Ranged reads of stream URLs (googlevideo), for the playback proxy and DASH probing.

Every upstream request is a `Range` request of at most `MAX_RANGE_BYTES`: googlevideo
throttles un-ranged GETs to a trickle (docs/spikes/0013-dash-ranges.md).
"""

import re
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator
from http.client import HTTPResponse
from types import TracebackType
from typing import Protocol, Self

from homefeed_core.gateway.errors import (
    ExtractionError,
    GatewayError,
    MediaUrlExpiredError,
    RangeNotSatisfiableError,
    RateLimitedError,
    UnavailableError,
)
from homefeed_core.gateway.models import ByteRange, Format

MAX_RANGE_BYTES = 10 * 1024 * 1024  # yt-dlp uses the same chunk size
READ_BLOCK_BYTES = 64 * 1024
TIMEOUT_SECONDS = 20

_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+|\*)$")


class MediaStream:
    """The body of one ranged read. Iterate it for the bytes, then close it.

    `byte_range` is what the server is sending (it may end before the requested end at
    the end of the file); `total` is the full file size, when known.
    """

    def __init__(
        self,
        byte_range: ByteRange,
        total: int | None,
        chunks: Iterable[bytes],
        close: Callable[[], None] = lambda: None,
    ) -> None:
        self.byte_range = byte_range
        self.total = total
        self._chunks = chunks
        self._close = close
        self._closed = False

    def __iter__(self) -> Iterator[bytes]:
        try:
            yield from self._chunks
        finally:
            self.close()

    def read(self) -> bytes:
        return b"".join(self)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def check_range(byte_range: ByteRange) -> None:
    length = byte_range.end - byte_range.start + 1
    if byte_range.start < 0 or length < 1 or length > MAX_RANGE_BYTES:
        raise ValueError(f"Ranges must be 1 to {MAX_RANGE_BYTES} bytes, got {byte_range}")


class MediaFetcher(Protocol):
    def __call__(self, fmt: Format, byte_range: ByteRange) -> MediaStream:
        """Start a ranged GET of `fmt.url`. Errors are raised before any body is read."""
        ...


OpenUrl = Callable[[urllib.request.Request, float], HTTPResponse]


def _urlopen(request: urllib.request.Request, timeout: float) -> HTTPResponse:
    return urllib.request.urlopen(request, timeout=timeout)


class HttpMediaFetcher:
    """`MediaFetcher` over HTTPS with urllib, sending the format's own HTTP headers."""

    def __init__(self, *, open_url: OpenUrl = _urlopen, timeout: float = TIMEOUT_SECONDS) -> None:
        self._open_url = open_url
        self._timeout = timeout

    def __call__(self, fmt: Format, byte_range: ByteRange) -> MediaStream:
        check_range(byte_range)
        headers = dict(fmt.http_headers) | {"Range": f"bytes={byte_range}"}
        request = urllib.request.Request(fmt.url, headers=headers)
        try:
            response = self._open_url(request, self._timeout)
        except urllib.error.HTTPError as error:
            raise media_http_error(error.code, fmt.itag) from error
        except (urllib.error.URLError, OSError) as error:
            raise ExtractionError(f"Could not fetch stream {fmt.itag}: {error}") from error
        try:
            served, total = _served_range(response, byte_range)
        except GatewayError:
            response.close()
            raise

        def chunks() -> Iterator[bytes]:
            while block := response.read(READ_BLOCK_BYTES):
                yield block

        return MediaStream(served, total, chunks(), response.close)


def media_http_error(status: int, itag: str) -> GatewayError:
    message = f"HTTP Error {status} fetching stream {itag}"
    if status in (401, 403, 410):
        return MediaUrlExpiredError(message)
    if status == 404:
        return UnavailableError(message)
    if status == 416:
        return RangeNotSatisfiableError(message)
    if status == 429:
        return RateLimitedError(message)
    return ExtractionError(message)


def _served_range(response: HTTPResponse, requested: ByteRange) -> tuple[ByteRange, int | None]:
    if response.status != 206:
        # A 200 would be the whole file, un-ranged and throttled: never stream that.
        raise ExtractionError(f"Expected a 206 for a ranged read, got {response.status}")
    match = _CONTENT_RANGE.match(response.headers.get("Content-Range", "").strip())
    if match is None:
        raise ExtractionError("Ranged read without a valid Content-Range")
    start, end, total = match.groups()
    served = ByteRange(int(start), int(end))
    if served.start != requested.start or served.end > requested.end:
        raise ExtractionError(f"Asked for bytes {requested}, got {served}")
    return served, None if total == "*" else int(total)
