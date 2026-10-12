"""An in-memory `Gateway` for tests of code that uses the Gateway.

gateway = FakeGateway()
channel = make_channel("UC" + "a" * 22, title="Woodworking", handle="@wood")
gateway.add_channel(channel, [make_video("aaaaaaaaaaa", channel=channel)])
gateway.add_related("aaaaaaaaaaa", [make_video("ccccccccccc", channel=channel)])
gateway.fail("get_video", "bbbbbbbbbbb", UnavailableError("removed"))

gateway.resolve_url("https://www.youtube.com/@wood")  # -> ResolvedChannel(channel)
gateway.calls  # [("resolve_url", "https://www.youtube.com/@wood")]

Stream bytes are served per URL: `gateway.add_media(fmt.url, data)`. Failures of
`open_media`/`probe_dash_ranges` are keyed by URL too.
"""

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from homefeed_core.gateway.dash import DashRanges, probe_dash_ranges
from homefeed_core.gateway.errors import GatewayError, RangeNotSatisfiableError, UnavailableError
from homefeed_core.gateway.interface import DEFAULT_RELATED_LIMIT, DEFAULT_UPLOADS_LIMIT
from homefeed_core.gateway.media import MediaStream, check_range
from homefeed_core.gateway.models import (
    ByteRange,
    Captions,
    CaptionSegment,
    Channel,
    ChannelUploads,
    Format,
    RelatedVideo,
    ResolvedChannel,
    ResolvedUrl,
    UploadSummary,
    Video,
)
from homefeed_core.gateway.urls import ChannelRef, channel_url, parse_youtube_url


class FakeGateway:
    """Serves videos, formats and channels added by the test; unknown ids are unavailable."""

    def __init__(self) -> None:
        self.videos: dict[str, Video] = {}
        self.formats: dict[str, list[Format]] = {}
        self.captions: dict[str, Captions] = {}
        self.channels: dict[str, Channel] = {}
        self.uploads: dict[str, list[UploadSummary]] = {}
        self.related: dict[str, list[RelatedVideo]] = {}
        self.urls: dict[str, ResolvedUrl] = {}
        self.failures: dict[tuple[str, str], GatewayError] = {}
        self.media: dict[str, bytes] = {}
        self.media_reads: list[tuple[str, ByteRange]] = []  # (url, range) per read
        self.calls: list[tuple[str, str]] = []

    # Setup

    def add_video(self, video: Video, formats: Iterable[Format] | None = None) -> None:
        self.videos[video.id] = video
        if formats is not None:
            self.formats[video.id] = list(formats)

    def add_captions(self, captions: Captions) -> None:
        """Serve `captions` for its video (add the video too); other videos have none."""
        self.captions[captions.video_id] = captions

    def add_related(self, video_id: str, videos: Iterable[Video]) -> None:
        """Make `videos` (added too) the related list of `video_id`, which must be added."""
        self.related[video_id] = []
        for video in videos:
            self.add_video(video)
            self.related[video_id].append(_related(video))

    def add_channel(self, channel: Channel, videos: Iterable[Video] = ()) -> None:
        """Add a channel whose uploads are `videos`, newest first (and add the videos)."""
        self.channels[channel.id] = channel
        self.uploads[channel.id] = []
        for video in videos:
            self.add_video(video)
            self.uploads[channel.id].append(_summary(video))

    def add_url(self, url: str, resolved: ResolvedUrl) -> None:
        """Make `resolve_url(url)` return `resolved`, overriding the default resolution."""
        self.urls[url] = resolved

    def add_media(self, url: str, data: bytes) -> None:
        """Serve `data` as the stream at `url` (a `Format.url`)."""
        self.media[url] = data

    def fail(self, operation: str, target: str, error: GatewayError) -> None:
        """Make `operation` (e.g. "get_video") raise `error` for `target` (id or URL)."""
        self.failures[(operation, target)] = error

    # Gateway

    def get_video(self, video_id: str) -> Video:
        self._call("get_video", video_id)
        if video_id not in self.videos:
            raise UnavailableError(f"Video unavailable: {video_id}")
        return self.videos[video_id]

    def get_formats(self, video_id: str) -> list[Format]:
        self._call("get_formats", video_id)
        if video_id not in self.videos:
            raise UnavailableError(f"Video unavailable: {video_id}")
        return list(self.formats.get(video_id, []))

    def get_captions(self, video_id: str) -> Captions | None:
        self._call("get_captions", video_id)
        if video_id not in self.videos:
            raise UnavailableError(f"Video unavailable: {video_id}")
        return self.captions.get(video_id)

    def get_related(
        self, video_id: str, *, limit: int = DEFAULT_RELATED_LIMIT
    ) -> list[RelatedVideo]:
        self._call("get_related", video_id)
        if video_id not in self.videos:
            raise UnavailableError(f"Video unavailable: {video_id}")
        return self.related.get(video_id, [])[:limit]

    def get_channel_uploads(
        self, channel_id: str, *, limit: int = DEFAULT_UPLOADS_LIMIT
    ) -> ChannelUploads:
        self._call("get_channel_uploads", channel_id)
        if channel_id not in self.channels:
            raise UnavailableError(f"This channel does not exist: {channel_id}")
        return ChannelUploads(self.channels[channel_id], self.uploads[channel_id][:limit])

    def resolve_url(self, url: str) -> ResolvedUrl:
        self._call("resolve_url", url)
        if url in self.urls:
            return self.urls[url]
        parsed = parse_youtube_url(url)
        if not isinstance(parsed, ChannelRef):
            return parsed
        for channel in self.channels.values():
            if parsed.channel_id == channel.id or (
                channel.handle and parsed.url.lower().endswith("/" + channel.handle.lower())
            ):
                return ResolvedChannel(channel)
        raise UnavailableError(f"This channel does not exist: {url}")

    def open_media(self, fmt: Format, byte_range: ByteRange) -> MediaStream:
        self._call("open_media", fmt.url)
        return self._read(fmt.url, byte_range)

    def probe_dash_ranges(self, fmt: Format) -> DashRanges | None:
        self._call("probe_dash_ranges", fmt.url)
        return probe_dash_ranges(lambda byte_range: self._read(fmt.url, byte_range).read())

    def _read(self, url: str, byte_range: ByteRange) -> MediaStream:
        check_range(byte_range)
        if url not in self.media:
            raise UnavailableError(f"No stream at {url}")
        data = self.media[url]
        if byte_range.start >= len(data):
            raise RangeNotSatisfiableError(f"{byte_range} is past the end ({len(data)} bytes)")
        self.media_reads.append((url, byte_range))
        served = ByteRange(byte_range.start, min(byte_range.end, len(data) - 1))
        body = data[served.start : served.end + 1]
        # Split the body like a network read would.
        blocks = (body[i : i + 4096] for i in range(0, len(body), 4096))
        return MediaStream(served, len(data), blocks)

    def _call(self, operation: str, target: str) -> None:
        self.calls.append((operation, target))
        error = self.failures.get((operation, target))
        if error is not None:
            raise error


def make_channel(channel_id: str = "UC" + "0" * 22, **fields: Any) -> Channel:
    defaults: dict[str, Any] = {"title": f"Channel {channel_id}", "url": channel_url(channel_id)}
    return Channel(id=channel_id, **(defaults | fields))


def make_video(
    video_id: str = "dQw4w9WgXcQ", *, channel: Channel | None = None, **fields: Any
) -> Video:
    channel = channel or make_channel()
    defaults: dict[str, Any] = {
        "title": f"Video {video_id}",
        "channel_id": channel.id,
        "channel_title": channel.title,
        "channel_handle": channel.handle,
        "duration_seconds": 600,
        "published_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    return Video(id=video_id, **(defaults | fields))


def make_format(itag: str = "140", **fields: Any) -> Format:
    defaults: dict[str, Any] = {
        "kind": "audio",
        "url": f"https://example.invalid/videoplayback?itag={itag}",
        "protocol": "https",
        "mime_type": "audio/mp4",
        "codecs": "mp4a.40.2",
        "bitrate": 128_000,
    }
    return Format(itag=itag, **(defaults | fields))


def make_captions(
    video_id: str = "dQw4w9WgXcQ",
    lines: Iterable[str] = ("Hello and welcome.",),
    *,
    seconds_per_line: float = 5.0,
    **fields: Any,
) -> Captions:
    """Captions with one segment per line, `seconds_per_line` apart."""
    segments = tuple(
        CaptionSegment(i * seconds_per_line, (i + 1) * seconds_per_line, line)
        for i, line in enumerate(lines)
    )
    defaults: dict[str, Any] = {"language": "en", "is_automatic": False}
    return Captions(video_id=video_id, segments=segments, **(defaults | fields))


def _summary(video: Video) -> UploadSummary:
    return UploadSummary(
        id=video.id,
        title=video.title,
        duration_seconds=video.duration_seconds,
        view_count=video.view_count,
        thumbnail_url=video.thumbnail_url,
        live_status=video.live_status,
    )


def _related(video: Video) -> RelatedVideo:
    return RelatedVideo(
        id=video.id,
        title=video.title,
        channel_id=video.channel_id,
        channel_title=video.channel_title,
        channel_handle=video.channel_handle,
        duration_seconds=video.duration_seconds,
        view_count=video.view_count,
        thumbnail_url=video.thumbnail_url,
        live_status=video.live_status,
    )
