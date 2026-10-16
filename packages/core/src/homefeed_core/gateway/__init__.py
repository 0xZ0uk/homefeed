"""The YouTube Gateway: the only module that talks to YouTube.

Use the `Gateway` protocol in type hints and `create_gateway()` to get the real
yt-dlp-backed implementation. Tests of other modules use `fake.FakeGateway`.
"""

from functools import partial

from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import get_session_factory
from homefeed_core.gateway.dash import DashRanges
from homefeed_core.gateway.errors import (
    CookiesError,
    ExtractionError,
    GatewayError,
    MediaUrlExpiredError,
    RangeNotSatisfiableError,
    RateLimitedError,
    UnavailableError,
    UnsupportedUrlError,
)
from homefeed_core.gateway.events import (
    EventRecorder,
    ExtractorEvent,
    MemoryEventRecorder,
    SqlEventRecorder,
)
from homefeed_core.gateway.interface import (
    DEFAULT_RELATED_LIMIT,
    DEFAULT_SEARCH_LIMIT,
    DEFAULT_UPLOADS_LIMIT,
    MAX_SEARCH_LIMIT,
    SEARCH_QUERY_MAX_LENGTH,
    Gateway,
    normalize_search_query,
)
from homefeed_core.gateway.media import MAX_RANGE_BYTES, HttpMediaFetcher, MediaFetcher, MediaStream
from homefeed_core.gateway.models import (
    ByteRange,
    Captions,
    CaptionSegment,
    Channel,
    ChannelUploads,
    Chapter,
    CookieCheck,
    FeaturedChannel,
    Format,
    FormatKind,
    LiveStatus,
    RelatedVideo,
    ResolvedChannel,
    ResolvedPlaylist,
    ResolvedUrl,
    ResolvedVideo,
    SearchDuration,
    SearchFilters,
    SearchResult,
    SearchSort,
    SearchUploadDate,
    UploadSummary,
    Video,
)
from homefeed_core.gateway.resilience import RateLimiter, RetryPolicy
from homefeed_core.gateway.rss import FeedFetcher, HttpFeedFetcher, channel_feed_url
from homefeed_core.gateway.ytdlp import YtDlpGateway, extract_info
from homefeed_core.user_settings import load_user_settings

__all__ = [
    "DEFAULT_RELATED_LIMIT",
    "DEFAULT_SEARCH_LIMIT",
    "DEFAULT_UPLOADS_LIMIT",
    "MAX_RANGE_BYTES",
    "MAX_SEARCH_LIMIT",
    "SEARCH_QUERY_MAX_LENGTH",
    "ByteRange",
    "CaptionSegment",
    "Captions",
    "Channel",
    "ChannelUploads",
    "Chapter",
    "CookieCheck",
    "CookiesError",
    "DashRanges",
    "EventRecorder",
    "ExtractionError",
    "ExtractorEvent",
    "FeaturedChannel",
    "FeedFetcher",
    "Format",
    "FormatKind",
    "Gateway",
    "GatewayError",
    "HttpFeedFetcher",
    "HttpMediaFetcher",
    "LiveStatus",
    "MediaFetcher",
    "MediaStream",
    "MediaUrlExpiredError",
    "MemoryEventRecorder",
    "RangeNotSatisfiableError",
    "RateLimitedError",
    "RateLimiter",
    "RelatedVideo",
    "ResolvedChannel",
    "ResolvedPlaylist",
    "ResolvedUrl",
    "ResolvedVideo",
    "RetryPolicy",
    "SearchDuration",
    "SearchFilters",
    "SearchResult",
    "SearchSort",
    "SearchUploadDate",
    "SqlEventRecorder",
    "UnavailableError",
    "UnsupportedUrlError",
    "UploadSummary",
    "Video",
    "YtDlpGateway",
    "channel_feed_url",
    "create_feed_fetcher",
    "create_gateway",
    "normalize_search_query",
]


def create_gateway(sessions: sessionmaker[Session] | None = None) -> Gateway:
    """The production Gateway, recording outcomes into `extractor_events` and sending
    YouTube cookies from the browser in the user settings (read on each call)."""
    sessions = sessions or get_session_factory()
    return YtDlpGateway(
        recorder=SqlEventRecorder(sessions),
        extract=partial(
            extract_info,
            cookies_from_browser=lambda: load_user_settings(sessions).ytdlp_cookies_from_browser,
        ),
    )


def create_feed_fetcher(sessions: sessionmaker[Session] | None = None) -> FeedFetcher:
    """The production channel RSS fetcher, recording outcomes into `extractor_events`."""
    return HttpFeedFetcher(recorder=SqlEventRecorder(sessions or get_session_factory()))
