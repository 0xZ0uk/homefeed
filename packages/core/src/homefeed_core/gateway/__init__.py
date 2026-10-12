"""The YouTube Gateway: the only module that talks to YouTube.

Use the `Gateway` protocol in type hints and `create_gateway()` to get the real
yt-dlp-backed implementation. Tests of other modules use `fake.FakeGateway`.
"""

from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import get_session_factory
from homefeed_core.gateway.dash import DashRanges
from homefeed_core.gateway.errors import (
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
from homefeed_core.gateway.interface import DEFAULT_RELATED_LIMIT, DEFAULT_UPLOADS_LIMIT, Gateway
from homefeed_core.gateway.media import MAX_RANGE_BYTES, HttpMediaFetcher, MediaFetcher, MediaStream
from homefeed_core.gateway.models import (
    ByteRange,
    Captions,
    CaptionSegment,
    Channel,
    ChannelUploads,
    Chapter,
    Format,
    FormatKind,
    LiveStatus,
    RelatedVideo,
    ResolvedChannel,
    ResolvedPlaylist,
    ResolvedUrl,
    ResolvedVideo,
    UploadSummary,
    Video,
)
from homefeed_core.gateway.resilience import RateLimiter, RetryPolicy
from homefeed_core.gateway.rss import FeedFetcher, HttpFeedFetcher, channel_feed_url
from homefeed_core.gateway.ytdlp import YtDlpGateway

__all__ = [
    "DEFAULT_RELATED_LIMIT",
    "DEFAULT_UPLOADS_LIMIT",
    "MAX_RANGE_BYTES",
    "ByteRange",
    "CaptionSegment",
    "Captions",
    "Channel",
    "ChannelUploads",
    "Chapter",
    "DashRanges",
    "EventRecorder",
    "ExtractionError",
    "ExtractorEvent",
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
    "SqlEventRecorder",
    "UnavailableError",
    "UnsupportedUrlError",
    "UploadSummary",
    "Video",
    "YtDlpGateway",
    "channel_feed_url",
    "create_feed_fetcher",
    "create_gateway",
]


def create_gateway(sessions: sessionmaker[Session] | None = None) -> Gateway:
    """The production Gateway, recording outcomes into `extractor_events`."""
    return YtDlpGateway(recorder=SqlEventRecorder(sessions or get_session_factory()))


def create_feed_fetcher(sessions: sessionmaker[Session] | None = None) -> FeedFetcher:
    """The production channel RSS fetcher, recording outcomes into `extractor_events`."""
    return HttpFeedFetcher(recorder=SqlEventRecorder(sessions or get_session_factory()))
