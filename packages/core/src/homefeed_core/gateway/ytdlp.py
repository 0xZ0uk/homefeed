"""The yt-dlp implementation of the Gateway. The only module that imports yt-dlp."""

import logging
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import yt_dlp
from yt_dlp.extractor.youtube import YoutubeIE
from yt_dlp.utils import DownloadError, ExtractorError

from homefeed_core.gateway.dash import DashRanges, probe_dash_ranges
from homefeed_core.gateway.errors import (
    ExtractionError,
    GatewayError,
    RateLimitedError,
    UnavailableError,
)
from homefeed_core.gateway.events import EventRecorder, ExtractorEvent
from homefeed_core.gateway.interface import DEFAULT_UPLOADS_LIMIT
from homefeed_core.gateway.media import HttpMediaFetcher, MediaFetcher, MediaStream
from homefeed_core.gateway.models import (
    ByteRange,
    ChannelUploads,
    Format,
    ResolvedChannel,
    ResolvedUrl,
    Video,
)
from homefeed_core.gateway.normalize import (
    Info,
    add_dash_ranges,
    channel_from_info,
    channel_uploads_from_info,
    dash_ranges,
    formats_from_info,
    video_from_info,
)
from homefeed_core.gateway.resilience import RateLimiter, RetryPolicy, Sleep, call_with_retries
from homefeed_core.gateway.urls import (
    CHANNEL_ID,
    VIDEO_ID,
    ChannelRef,
    channel_url,
    parse_youtube_url,
    video_url,
)

logger = logging.getLogger(__name__)

SOCKET_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class ExtractRequest:
    """One extractor call. `flat` lists playlist/channel entries without resolving each."""

    url: str
    flat: bool = False
    limit: int | None = None  # max entries when `flat`


Extract = Callable[[ExtractRequest], dict[str, Any]]


def extract_info(request: ExtractRequest) -> dict[str, Any]:
    """Run yt-dlp for `request` and return its JSON-safe info dict.

    yt-dlp's exceptions are translated into `GatewayError`s here, so nothing above
    this function knows yt-dlp exists.
    """
    options: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": not request.flat,
        "socket_timeout": SOCKET_TIMEOUT_SECONDS,
        "extractor_retries": 1,  # the Gateway retries with its own backoff
        "logger": _YtDlpLogger(),
    }
    if request.flat:
        options["extract_flat"] = "in_playlist"
        if request.limit is not None:
            options["playlistend"] = request.limit
    try:
        with yt_dlp.YoutubeDL(options) as ydl:  # pyright: ignore[reportArgumentType]
            ydl.add_info_extractor(_DashRangesYoutubeIE())  # pyright: ignore[reportArgumentType]
            info = ydl.extract_info(request.url, download=False)
            return dict(ydl.sanitize_info(info) or {})
    except (DownloadError, ExtractorError) as error:
        raise classify_error(str(error)) from error
    except GatewayError:
        raise
    except Exception as error:  # yt-dlp bugs surface as arbitrary exceptions
        raise ExtractionError(f"yt-dlp failed: {error!r}") from error


_UNAVAILABLE_MARKERS = (
    "video unavailable",
    "video is unavailable",
    "private video",
    "has been removed",
    "does not exist",
    "is not available",
    "not made this video available",
    "account associated with this video has been terminated",
    "this channel does not have a",
    "confirm your age",
    "members-only",
    "join this channel",
    "this live event will begin",
    "premieres in",
    "http error 404",
)
_RATE_LIMIT_MARKERS = (
    "http error 429",
    "too many requests",
    "not a bot",
    "rate-limited",
    "rate limited",
)


def classify_error(message: str) -> GatewayError:
    """Map a yt-dlp error message to the matching `GatewayError`."""
    text = message.removeprefix("ERROR: ").strip()
    lowered = text.lower().replace("’", "'")
    if any(marker in lowered for marker in _RATE_LIMIT_MARKERS):
        return RateLimitedError(text)
    if any(marker in lowered for marker in _UNAVAILABLE_MARKERS):
        return UnavailableError(text)
    return ExtractionError(text)


class YtDlpGateway:
    """`Gateway` backed by yt-dlp, with retries, rate limiting and event recording.

    `extract` is the seam for tests: pass a function that replays recorded responses,
    and `media` the one for stream reads. Stream reads are not rate limited or retried
    (the player retries), and only failures are recorded, since a video plays as
    hundreds of them.
    """

    def __init__(
        self,
        *,
        recorder: EventRecorder | None = None,
        retry: RetryPolicy | None = None,
        rate_limiter: RateLimiter | None = None,
        extract: Extract = extract_info,
        media: MediaFetcher | None = None,
        sleep: Sleep = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        rng: random.Random | None = None,
    ) -> None:
        self._recorder = recorder
        self._retry = retry or RetryPolicy()
        self._rate_limiter = rate_limiter or RateLimiter()
        self._extract = extract
        self._media = media or HttpMediaFetcher()
        self._sleep = sleep
        self._now = now
        self._rng = rng or random.Random()

    def get_video(self, video_id: str) -> Video:
        _check_video_id(video_id)
        request = ExtractRequest(video_url(video_id))
        return self._run("get_video", video_id, request, video_from_info)

    def get_formats(self, video_id: str) -> list[Format]:
        _check_video_id(video_id)
        request = ExtractRequest(video_url(video_id))
        return self._run("get_formats", video_id, request, formats_from_info)

    def get_channel_uploads(
        self, channel_id: str, *, limit: int = DEFAULT_UPLOADS_LIMIT
    ) -> ChannelUploads:
        if not CHANNEL_ID.match(channel_id):
            raise UnavailableError(f"Not a channel id: {channel_id!r}")
        if limit < 1:
            raise ValueError("limit must be at least 1")
        request = ExtractRequest(f"{channel_url(channel_id)}/videos", flat=True, limit=limit)
        return self._run("get_channel_uploads", channel_id, request, channel_uploads_from_info)

    def resolve_url(self, url: str) -> ResolvedUrl:
        parsed = parse_youtube_url(url)
        if not isinstance(parsed, ChannelRef):
            return parsed
        # Any channel URL form: fetch one upload's worth of the videos tab for the metadata.
        request = ExtractRequest(f"{parsed.url}/videos", flat=True, limit=1)
        channel = self._run("resolve_url", url, request, channel_from_info)
        return ResolvedChannel(channel)

    def open_media(self, fmt: Format, byte_range: ByteRange) -> MediaStream:
        started_at, started = self._now(), time.monotonic()
        try:
            return self._media(fmt, byte_range)
        except GatewayError as error:
            self._record("open_media", fmt.itag, started_at, started, 1, error)
            raise

    def probe_dash_ranges(self, fmt: Format) -> DashRanges | None:
        started_at, started = self._now(), time.monotonic()
        reads = 0

        def fetch(byte_range: ByteRange) -> bytes:
            nonlocal reads
            reads += 1
            with self._media(fmt, byte_range) as stream:
                return stream.read()

        try:
            ranges = probe_dash_ranges(fetch)
        except GatewayError as error:
            self._record("probe_dash_ranges", fmt.itag, started_at, started, reads, error)
            raise
        self._record("probe_dash_ranges", fmt.itag, started_at, started, reads, None)
        return ranges

    def _run[T](
        self,
        operation: str,
        target: str,
        request: ExtractRequest,
        normalize: Callable[[Info], T],
    ) -> T:
        started_at = self._now()
        started = time.monotonic()
        attempts = 0

        def attempt() -> dict[str, Any]:
            self._rate_limiter.wait()
            return self._extract(request)

        def count(n: int) -> None:
            nonlocal attempts
            attempts = n

        try:
            info = call_with_retries(
                attempt, self._retry, sleep=self._sleep, rng=self._rng, on_attempt=count
            )
            result = normalize(info)
        except GatewayError as error:
            self._record(operation, target, started_at, started, attempts, error)
            raise
        except Exception as error:
            wrapped = ExtractionError(f"Unexpected extractor response: {error!r}")
            self._record(operation, target, started_at, started, attempts, wrapped)
            raise wrapped from error
        self._record(operation, target, started_at, started, attempts, None)
        return result

    def _record(
        self,
        operation: str,
        target: str,
        at: datetime,
        started: float,
        attempts: int,
        error: GatewayError | None,
    ) -> None:
        if self._recorder is None:
            return
        self._recorder.record(
            ExtractorEvent(
                operation=operation,
                target=target,
                success=error is None,
                at=at,
                attempts=max(attempts, 1),
                duration_ms=round((time.monotonic() - started) * 1000),
                error_kind=error.kind if error else None,
                error=str(error) if error else None,
            )
        )


def _check_video_id(video_id: str) -> None:
    if not VIDEO_ID.match(video_id):
        raise UnavailableError(f"Not a video id: {video_id!r}")


class _DashRangesYoutubeIE(YoutubeIE):
    """yt-dlp's YouTube extractor, keeping the DASH init/index byte ranges.

    InnerTube returns `initRange`/`indexRange` for every adaptive stream but yt-dlp does
    not put them in its format dicts. This wraps the (private) method that turns player
    responses into formats and copies the ranges onto each format as `init_range` and
    `index_range`. If a yt-dlp update changes that method, formats simply come back
    without ranges, which the playback service must tolerate (see docs/spikes/0013).
    """

    @classmethod
    def ie_key(cls) -> str:
        return YoutubeIE.ie_key()  # replace the stock extractor, keep its name

    def _extract_formats_and_subtitles(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, video_id: str, player_responses: list[Any], *args: Any, **kwargs: Any
    ) -> Iterator[Any]:
        try:
            ranges = dash_ranges(player_responses)
        except Exception:  # never let the range bookkeeping break extraction
            logger.warning("Could not read DASH ranges for %s", video_id, exc_info=True)
            ranges = {}
        for item in super()._extract_formats_and_subtitles(  # pyright: ignore[reportUnknownMemberType]
            video_id, player_responses, *args, **kwargs
        ):
            if ranges and isinstance(item, dict) and "format_id" in item:
                add_dash_ranges(item, ranges)  # pyright: ignore[reportUnknownArgumentType]
            yield item


class _YtDlpLogger:
    """Route yt-dlp output to logging; errors are raised and recorded, so keep them quiet."""

    def debug(self, message: str) -> None:
        logger.debug(message)

    def info(self, message: str) -> None:
        logger.debug(message)

    def warning(self, message: str) -> None:
        logger.warning(message)

    def error(self, message: str) -> None:
        logger.debug(message)
