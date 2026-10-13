from typing import Protocol

from homefeed_core.gateway.dash import DashRanges
from homefeed_core.gateway.media import MediaStream
from homefeed_core.gateway.models import (
    ByteRange,
    Captions,
    ChannelUploads,
    FeaturedChannel,
    Format,
    RelatedVideo,
    ResolvedUrl,
    SearchFilters,
    SearchResult,
    Video,
)

DEFAULT_UPLOADS_LIMIT = 30
DEFAULT_RELATED_LIMIT = 20
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 50
SEARCH_QUERY_MAX_LENGTH = 200


def normalize_search_query(query: str) -> str:
    """Trim and collapse inner whitespace. Raises `ValueError` if nothing is left or the
    result is longer than `SEARCH_QUERY_MAX_LENGTH`."""
    normalized = " ".join(query.split())
    if not normalized:
        raise ValueError("Search query is empty")
    if len(normalized) > SEARCH_QUERY_MAX_LENGTH:
        raise ValueError(f"Search query is longer than {SEARCH_QUERY_MAX_LENGTH} characters")
    return normalized


def check_search_limit(limit: int) -> None:
    if not 1 <= limit <= MAX_SEARCH_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_SEARCH_LIMIT}")


class Gateway(Protocol):
    """The only way into YouTube.

    Every method either returns normalized dataclasses or raises a `GatewayError`
    subclass. Retries, rate limiting and failure recording happen inside.
    """

    def get_video(self, video_id: str) -> Video:
        """Full metadata for one video. Raises `UnavailableError` if it can't be watched."""
        ...

    def get_formats(self, video_id: str) -> list[Format]:
        """Playable streams for a video. URLs expire; see `Format.expires_at`."""
        ...

    def get_captions(self, video_id: str) -> Captions | None:
        """One caption track of a video, preferring English; None if it has no captions.

        Raises `UnavailableError` if the video can't be watched.
        """
        ...

    def get_related(
        self, video_id: str, *, limit: int = DEFAULT_RELATED_LIMIT
    ) -> list[RelatedVideo]:
        """Up to `limit` videos YouTube suggests next to a video (its watch page's
        related list), in YouTube's order. Playlists, mixes and Shorts shelves are left
        out. Raises `UnavailableError` if the video can't be watched.
        """
        ...

    def search(
        self,
        query: str,
        filters: SearchFilters | None = None,
        *,
        limit: int = DEFAULT_SEARCH_LIMIT,
    ) -> list[SearchResult]:
        """Up to `limit` (at most `MAX_SEARCH_LIMIT`) videos YouTube finds for `query`,
        in its order, narrowed by `filters`. Raises `ValueError` for a blank or too long
        query (see `normalize_search_query`).
        """
        ...

    def get_channel_uploads(
        self, channel_id: str, *, limit: int = DEFAULT_UPLOADS_LIMIT
    ) -> ChannelUploads:
        """The channel and its most recent `limit` uploads (videos tab), newest first."""
        ...

    def get_featured_channels(self, channel_id: str) -> list[FeaturedChannel]:
        """The channels a channel features on its home tab, in its order, without
        duplicates or the channel itself. Empty when it features none. Raises
        `UnavailableError` if the channel doesn't exist.
        """
        ...

    def resolve_url(self, url: str) -> ResolvedUrl:
        """Identify what a YouTube URL (video, channel, playlist) points to.

        Channel URLs in any form (`/@handle`, `/c/name`, `/user/name`, `/channel/UC...`)
        resolve to the canonical channel. Raises `UnsupportedUrlError` for anything else.
        """
        ...

    def open_media(self, fmt: Format, byte_range: ByteRange) -> MediaStream:
        """Start a ranged read of one stream (from `get_formats`), at most 10 MB.

        Raises `MediaUrlExpiredError` when the URL was refused (expired or revoked: get
        fresh formats and retry), `RangeNotSatisfiableError` past the end of the file,
        and `ValueError` for an empty or too large range. Errors are raised before any
        body is read; close the returned stream when done.
        """
        ...

    def probe_dash_ranges(self, fmt: Format) -> DashRanges | None:
        """Find an adaptive stream's (init, index) byte ranges by reading its first KB.

        For formats that came without `init_range`/`index_range`. Returns None when the
        file's layout isn't one we can read; raises like `open_media` otherwise.
        """
        ...
