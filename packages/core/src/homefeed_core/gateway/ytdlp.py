"""The yt-dlp implementation of the Gateway. The only module that imports yt-dlp."""

import base64
import json
import logging
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import quote, urlencode

import yt_dlp
from yt_dlp.extractor.youtube import YoutubeIE, YoutubeTabIE
from yt_dlp.networking.exceptions import HTTPError
from yt_dlp.utils import DownloadError, ExtractorError, parse_count

from homefeed_core.gateway.dash import DashRanges, probe_dash_ranges
from homefeed_core.gateway.errors import (
    ExtractionError,
    GatewayError,
    RateLimitedError,
    UnavailableError,
)
from homefeed_core.gateway.events import EventRecorder, ExtractorEvent
from homefeed_core.gateway.interface import (
    DEFAULT_RELATED_LIMIT,
    DEFAULT_SEARCH_LIMIT,
    DEFAULT_UPLOADS_LIMIT,
    check_search_limit,
    normalize_search_query,
)
from homefeed_core.gateway.media import HttpMediaFetcher, MediaFetcher, MediaStream
from homefeed_core.gateway.models import (
    ByteRange,
    Captions,
    ChannelUploads,
    FeaturedChannel,
    Format,
    RelatedVideo,
    ResolvedChannel,
    ResolvedUrl,
    SearchFilters,
    SearchResult,
    Video,
)
from homefeed_core.gateway.normalize import (
    Info,
    add_dash_ranges,
    captions_from_info,
    channel_from_info,
    channel_uploads_from_info,
    dash_ranges,
    featured_channels_from_info,
    formats_from_info,
    pick_caption_track,
    related_from_info,
    search_results_from_info,
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
    """One extractor call. `flat` lists playlist/channel entries without resolving each;
    `captions` returns a video's chosen caption track instead of its info (see
    `normalize.pick_caption_track`); `related` returns the videos suggested next to it
    (see `_download_related`); `featured` returns the channels a channel features (see
    `_download_featured`)."""

    url: str
    flat: bool = False
    limit: int | None = None  # max entries when `flat`
    captions: bool = False
    related: bool = False
    featured: bool = False


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
            if request.related:
                return _download_related(ydl, request.url)
            if request.featured:
                return _download_featured(ydl, request.url)
            info = dict(ydl.sanitize_info(ydl.extract_info(request.url, download=False)) or {})
            return _download_captions(ydl, info) if request.captions else info
    except (DownloadError, ExtractorError) as error:
        raise classify_error(str(error)) from error
    except HTTPError as error:
        raise classify_error(f"HTTP Error {error.status}: {error.reason}") from error
    except GatewayError:
        raise
    except Exception as error:  # yt-dlp bugs surface as arbitrary exceptions
        raise ExtractionError(f"yt-dlp failed: {error!r}") from error


def _download_captions(ydl: yt_dlp.YoutubeDL, info: dict[str, Any]) -> dict[str, Any]:
    """Fetch the json3 track `pick_caption_track` chooses, through yt-dlp's HTTP stack."""
    track = pick_caption_track(info)
    if track is None:
        return {"id": info.get("id"), "captions": None}
    with ydl.urlopen(track.url) as response:
        data = json.loads(response.read())
    events = data.get("events") if isinstance(data, dict) else None
    return {
        "id": info.get("id"),
        "captions": {
            "language": track.language,
            "automatic": track.is_automatic,
            "events": events if isinstance(events, list) else [],
        },
    }


# The fields of yt-dlp's flat entries that `normalize.related_from_info` reads.
_RELATED_KEYS = (
    "id",
    "title",
    "channel_id",
    "channel",
    "uploader_id",
    "duration",
    "view_count",
    "thumbnails",
    "live_status",
)
_LOCKUP_CHANNEL = (
    "metadata",
    "lockupMetadataViewModel",
    "image",
    "decoratedAvatarViewModel",
    "rendererContext",
    "commandContext",
    "onTap",
    "innertubeCommand",
    "browseEndpoint",
)
_LOCKUP_FIRST_LINE = (
    "metadata",
    "lockupMetadataViewModel",
    "metadata",
    "contentMetadataViewModel",
    "metadataRows",
    0,
    "metadataParts",
    0,
    "text",
    "content",
)


def _download_related(ydl: yt_dlp.YoutubeDL, url: str) -> dict[str, Any]:
    """The watch page's related list, as {"id": <video id>, "entries": [flat entries]}.

    yt-dlp no longer extracts related videos, so this asks InnerTube's `next` endpoint
    (the data behind the watch page) through yt-dlp's (private) API helper, which brings
    its client context, consent cookies and error handling, and turns each video lockup
    into a flat entry with yt-dlp's own channel-tab parser. That parser misses the
    channel on watch-page lockups, so the channel is read from the lockup's avatar.
    """
    youtube: Any = ydl.get_info_extractor(YoutubeIE.ie_key())
    youtube.initialize()
    video_id: str = youtube._match_id(url)
    data = youtube._extract_response(
        item_id=video_id,
        query={"videoId": video_id},
        ep="next",
        note="Downloading related videos",
    )
    watch_next = _dig(data, "contents", "twoColumnWatchNextResults")
    if not isinstance(watch_next, dict):
        raise ExtractionError(f"No watch page data for {video_id}")
    results = _dig(watch_next, "secondaryResults", "secondaryResults", "results")
    if not isinstance(results, list):
        # Unavailable videos get a "This video isn't available anymore" page instead.
        promo = _find(watch_next, "backgroundPromoRenderer")
        if promo is not None:
            runs = _dig(promo, "title", "runs")
            reason = "".join(
                str(run.get("text", ""))
                for run in cast(list[Any], runs if isinstance(runs, list) else [])
                if isinstance(run, dict)
            )
            raise classify_error(f"Video unavailable: {reason or 'no related videos'}")
        results = []
    tab: Any = ydl.get_info_extractor(YoutubeTabIE.ie_key())
    entries: list[dict[str, Any]] = []
    for item in cast(list[Any], results):
        lockup = _dig(item, "lockupViewModel")
        # Skip continuations, Shorts shelves, playlists and mixes.
        if not isinstance(lockup, dict):
            continue
        lockup = cast(dict[str, Any], lockup)
        if lockup.get("contentType") != "LOCKUP_CONTENT_TYPE_VIDEO":
            continue
        parsed = tab._extract_lockup_view_model(lockup)
        if not isinstance(parsed, dict):
            continue
        entry = cast(dict[str, Any], parsed)
        channel = _dig(lockup, *_LOCKUP_CHANNEL)
        channel = cast(dict[str, Any], channel) if isinstance(channel, dict) else {}
        handle = str(channel.get("canonicalBaseUrl") or "").lstrip("/")
        entry["channel_id"] = entry.get("channel_id") or channel.get("browseId")
        entry["channel"] = entry.get("channel") or _dig(lockup, *_LOCKUP_FIRST_LINE)
        if not entry.get("uploader_id") and handle.startswith("@"):
            entry["uploader_id"] = handle
        entries.append({key: entry.get(key) for key in _RELATED_KEYS})
    return {"id": video_id, "entries": entries}


_CHANNEL_RENDERERS = ("gridChannelRenderer", "channelRenderer")


def _download_featured(ydl: yt_dlp.YoutubeDL, url: str) -> dict[str, Any]:
    """The channels a channel features, as {"id": <channel id>, "entries": [...]}.

    YouTube dropped the "Channels" tab that yt-dlp reads featured channels from; they
    now show as shelves of channel renderers on the home tab. This asks InnerTube's
    `browse` endpoint for the home tab through yt-dlp's (private) API helper and turns
    every channel renderer on it into a flat entry, in page order.
    """
    channel_id = url.rstrip("/").rsplit("/", 1)[-1]
    if not CHANNEL_ID.match(channel_id):
        raise ExtractionError(f"Not a channel URL: {url}")
    tab: Any = ydl.get_info_extractor(YoutubeTabIE.ie_key())
    tab.initialize()
    data = tab._extract_response(
        item_id=channel_id,
        query={"browseId": channel_id},
        ep="browse",
        note="Downloading featured channels",
    )
    if not isinstance(data, dict) or not isinstance(_dig(data, "contents"), dict):
        raise ExtractionError(f"No channel page data for {channel_id}")
    entries: list[dict[str, Any]] = []
    for renderer in _find_all(data, _CHANNEL_RENDERERS):
        featured_id = renderer.get("channelId")
        if not isinstance(featured_id, str):
            continue
        base_url = _dig(renderer, "navigationEndpoint", "browseEndpoint", "canonicalBaseUrl")
        handle = str(base_url or "").lstrip("/")
        thumbnails = _dig(renderer, "thumbnail", "thumbnails")
        entries.append(
            {
                "id": featured_id,
                "title": _text(renderer.get("title")),
                "uploader_id": handle if handle.startswith("@") else None,
                "thumbnails": [
                    {**thumb, "url": "https:" + thumb["url"]}
                    if str(thumb.get("url", "")).startswith("//")
                    else thumb
                    for thumb in cast(list[Any], thumbnails if isinstance(thumbnails, list) else [])
                    if isinstance(thumb, dict)
                ],
                "channel_follower_count": parse_count(_text(renderer.get("subscriberCountText"))),
                "video_count": parse_count(_text(renderer.get("videoCountText"))),
            }
        )
    return {"id": channel_id, "entries": entries}


def _text(value: Any) -> str | None:
    """The text of an InnerTube text object ({"simpleText": ...} or {"runs": [...]})."""
    if not isinstance(value, dict):
        return None
    mapping = cast(dict[str, Any], value)
    if isinstance(mapping.get("simpleText"), str):
        return mapping["simpleText"]
    runs = mapping.get("runs")
    if isinstance(runs, list):
        return "".join(
            str(run.get("text", "")) for run in cast(list[Any], runs) if isinstance(run, dict)
        )
    return None


def _find_all(value: Any, keys: tuple[str, ...]) -> Iterator[dict[str, Any]]:
    """Every dict under one of `keys` anywhere in nested dicts and lists, in order."""
    if isinstance(value, dict):
        for key, child in cast(dict[str, Any], value).items():
            if key in keys and isinstance(child, dict):
                yield cast(dict[str, Any], child)
            else:
                yield from _find_all(child, keys)
    elif isinstance(value, list):
        for child in cast(list[Any], value):
            yield from _find_all(child, keys)


def _dig(value: Any, *path: str | int) -> Any:
    """`value[path[0]][path[1]]...`, or None where the path doesn't exist."""
    for key in path:
        if isinstance(key, int) and isinstance(value, list) and -len(value) <= key < len(value):
            value = cast(list[Any], value)[key]
        elif isinstance(key, str) and isinstance(value, dict):
            value = cast(dict[str, Any], value).get(key)
        else:
            return None
    return value


def _find(value: Any, key: str) -> Any:
    """The first value under `key` anywhere in nested dicts and lists, or None."""
    if isinstance(value, dict):
        mapping = cast(dict[str, Any], value)
        if key in mapping:
            return mapping[key]
        children: list[Any] = list(mapping.values())
    elif isinstance(value, list):
        children = cast(list[Any], value)
    else:
        return None
    for child in children:
        found = _find(child, key)
        if found is not None:
            return found
    return None


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

    def get_captions(self, video_id: str) -> Captions | None:
        _check_video_id(video_id)
        request = ExtractRequest(video_url(video_id), captions=True)
        return self._run("get_captions", video_id, request, captions_from_info)

    def get_related(
        self, video_id: str, *, limit: int = DEFAULT_RELATED_LIMIT
    ) -> list[RelatedVideo]:
        _check_video_id(video_id)
        if limit < 1:
            raise ValueError("limit must be at least 1")
        request = ExtractRequest(video_url(video_id), related=True)
        return self._run(
            "get_related", video_id, request, lambda info: related_from_info(info)[:limit]
        )

    def search(
        self,
        query: str,
        filters: SearchFilters | None = None,
        *,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[SearchResult]:
        query = normalize_search_query(query)
        check_search_limit(limit)
        request = ExtractRequest(search_url(query, filters, limit), flat=True, limit=limit)
        return self._run(
            "search", query, request, lambda info: search_results_from_info(info)[:limit]
        )

    def get_channel_uploads(
        self, channel_id: str, *, limit: int = DEFAULT_UPLOADS_LIMIT
    ) -> ChannelUploads:
        if not CHANNEL_ID.match(channel_id):
            raise UnavailableError(f"Not a channel id: {channel_id!r}")
        if limit < 1:
            raise ValueError("limit must be at least 1")
        request = ExtractRequest(f"{channel_url(channel_id)}/videos", flat=True, limit=limit)
        return self._run("get_channel_uploads", channel_id, request, channel_uploads_from_info)

    def get_featured_channels(self, channel_id: str) -> list[FeaturedChannel]:
        if not CHANNEL_ID.match(channel_id):
            raise UnavailableError(f"Not a channel id: {channel_id!r}")
        request = ExtractRequest(channel_url(channel_id), featured=True)
        return self._run("get_featured_channels", channel_id, request, featured_channels_from_info)

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


# YouTube's search filters travel in the results page's `sp` parameter: a base64
# protobuf message with the sort order as field 1 and the filters as message field 2
# (upload date = 1, result type = 2, duration = 3).
_SORT_VALUES = {"relevance": 0, "rating": 1, "upload_date": 2, "view_count": 3}
_UPLOAD_DATE_VALUES = {"hour": 1, "today": 2, "week": 3, "month": 4, "year": 5}
_DURATION_VALUES = {"short": 1, "long": 2, "medium": 3}
_TYPE_VIDEO = 1


def search_url(query: str, filters: SearchFilters | None, limit: int) -> str:
    """What yt-dlp is asked for: `ytsearchN:<query>` for a plain search, or YouTube's
    results page with the filters encoded in `sp` otherwise."""
    if filters is None or filters.is_default:
        return f"ytsearch{limit}:{query}"
    params = urlencode({"search_query": query, "sp": search_params(filters)}, quote_via=quote)
    return f"https://www.youtube.com/results?{params}"


def search_params(filters: SearchFilters) -> str:
    """The `sp` value for `filters` (results are always restricted to videos)."""
    nested = bytes([0x10, _TYPE_VIDEO])  # field 2 (type) = video
    if filters.upload_date is not None:
        nested = bytes([0x08, _UPLOAD_DATE_VALUES[filters.upload_date]]) + nested
    if filters.duration is not None:
        nested += bytes([0x18, _DURATION_VALUES[filters.duration]])
    message = bytes([0x12, len(nested)]) + nested  # field 2 (filters)
    sort = _SORT_VALUES[filters.sort]
    if sort:
        message = bytes([0x08, sort]) + message  # field 1 (sort)
    return base64.b64encode(message).decode()


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
