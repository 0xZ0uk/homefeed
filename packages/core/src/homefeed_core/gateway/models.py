"""Normalized domain dataclasses returned by the Gateway.

These carry no yt-dlp types, so the rest of the system never sees an extractor's raw
response. All datetimes are timezone-aware UTC.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

LiveStatus = Literal["not_live", "is_live", "is_upcoming", "was_live", "post_live"]
FormatKind = Literal["video", "audio", "muxed"]


@dataclass(frozen=True)
class Chapter:
    title: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class Channel:
    id: str  # UC...
    title: str
    handle: str | None = None  # e.g. "@somechannel"
    url: str | None = None
    thumbnail_url: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class Video:
    id: str
    title: str
    channel_id: str
    channel_title: str
    channel_handle: str | None = None
    description: str | None = None
    duration_seconds: int | None = None
    published_at: datetime | None = None
    thumbnail_url: str | None = None
    live_status: LiveStatus = "not_live"
    is_short: bool = False
    view_count: int | None = None
    tags: tuple[str, ...] = ()
    chapters: tuple[Chapter, ...] = ()


@dataclass(frozen=True)
class ByteRange:
    """An inclusive byte range, as used by DASH `indexRange` and `Initialization@range`."""

    start: int
    end: int

    def __str__(self) -> str:
        return f"{self.start}-{self.end}"


@dataclass(frozen=True)
class Format:
    """One stream of a video. `itag` is YouTube's format id (e.g. "140", "251-drc")."""

    itag: str
    kind: FormatKind
    url: str
    protocol: str  # "https" for progressive/adaptive, "m3u8_native" for HLS
    mime_type: str  # e.g. "audio/mp4"
    codecs: str  # e.g. "mp4a.40.2", or "avc1.4D401E, mp4a.40.2" for muxed
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    bitrate: int | None = None  # bits per second
    filesize: int | None = None  # bytes
    audio_sample_rate: int | None = None
    audio_channels: int | None = None
    language: str | None = None
    dynamic_range: str | None = None  # "SDR", "HDR10", ...
    is_drc: bool = False  # dynamic range compressed audio
    note: str | None = None  # e.g. "720p", "medium"
    expires_at: datetime | None = None  # when `url` stops working
    http_headers: Mapping[str, str] = field(default_factory=dict[str, str])
    # Adaptive (DASH) streams only: the header bytes (ftyp+moov / EBML+Tracks) and the
    # segment index (mp4 `sidx` / webm `Cues`). Needed for a SegmentBase DASH manifest.
    init_range: ByteRange | None = None
    index_range: ByteRange | None = None


@dataclass(frozen=True)
class UploadSummary:
    """A video as listed on a channel page; fetch `get_video` for full metadata."""

    id: str
    title: str
    duration_seconds: int | None = None
    view_count: int | None = None
    thumbnail_url: str | None = None
    published_at: datetime | None = None  # channel listings usually omit it
    live_status: LiveStatus | None = None


@dataclass(frozen=True)
class ChannelUploads:
    channel: Channel
    videos: list[UploadSummary]  # newest first


@dataclass(frozen=True)
class ResolvedVideo:
    video_id: str
    start_seconds: int | None = None
    is_short_url: bool = False  # the URL was a /shorts/ link


@dataclass(frozen=True)
class ResolvedChannel:
    channel: Channel


@dataclass(frozen=True)
class ResolvedPlaylist:
    playlist_id: str


ResolvedUrl = ResolvedVideo | ResolvedChannel | ResolvedPlaylist
