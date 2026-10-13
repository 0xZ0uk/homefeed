"""Playback: a DASH manifest for a video, a byte-range proxy for its streams, and the
SponsorBlock segments the player skips.

The manifest lists YouTube's adaptive streams as they are (SegmentBase: the init and
index byte ranges of each file, see docs/spikes/0013-dash-ranges.md), with `BaseURL`s
pointing at our own media proxy, `media/{format_id}`, relative to the manifest. So the
manifest never contains a googlevideo URL and stays valid after those URLs expire
(about 6 hours): `proxy_range` re-resolves them through the Gateway when they are
about to expire or upstream refuses them.

Streams are identified by yt-dlp's format id (`Format.itag`), e.g. "140", "140-drc"
or "251-1" for a dubbed track, since a bare itag can name several files.

    playback = Playback(gateway)
    playback.manifest("dQw4w9WgXcQ")            # -> MPD XML
    response = playback.proxy_range("dQw4w9WgXcQ", "137", "bytes=0-1023")
    response.status, response.headers, b"".join(response.body)
    playback.sponsor_segments("dQw4w9WgXcQ")   # -> [SponsorSegment(...), ...]
"""

import re
import threading
import xml.etree.ElementTree as ET
from collections import OrderedDict
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

from homefeed_core.gateway import (
    MAX_RANGE_BYTES,
    ByteRange,
    Format,
    Gateway,
    GatewayError,
    MediaStream,
    MediaUrlExpiredError,
    RangeNotSatisfiableError,
    Video,
)
from homefeed_core.sponsorblock import HttpSponsorBlock, SponsorBlock, SponsorSegment

MPD_CONTENT_TYPE = "application/dash+xml"

# Re-resolve stream URLs this long before they expire, so a read never races expiry.
URL_REFRESH_MARGIN = timedelta(minutes=30)
# How long to trust formats whose URLs carry no expiry, and video metadata.
FORMATS_TTL = timedelta(hours=1)
VIDEO_TTL = timedelta(hours=6)
# SponsorBlock segments are submitted over time, so they're re-fetched hourly.
SEGMENTS_TTL = timedelta(hours=1)
MIN_FORMATS_TTL = timedelta(minutes=1)
# Videos whose formats/metadata are kept in memory (least recently used are dropped).
CACHED_VIDEOS = 64
PROBE_WORKERS = 8

_MPD_NS = "urn:mpeg:dash:schema:mpd:2011"
_AUDIO_CHANNELS_SCHEME = "urn:mpeg:dash:23003:3:audio_channel_configuration:2011"
_ROLE_SCHEME = "urn:mpeg:dash:role:2011"
_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


class PlaybackError(Exception):
    """Base class for playback failures that aren't Gateway errors."""


class NoPlayableStreamsError(PlaybackError):
    """The video has no adaptive streams we can put in a manifest (e.g. it's live)."""


class StreamNotFoundError(PlaybackError):
    """The video has no adaptive stream with that format id."""


class StreamChangedError(PlaybackError):
    """YouTube replaced the file behind a format id; reload the manifest.

    The byte ranges in an open manifest belong to the old file, so serving the new one
    would hand the player mismatched bytes.
    """


class RangeNotSatisfiable(PlaybackError):
    """The requested range is outside the stream. `total` is its size, when known."""

    def __init__(self, message: str, total: int | None) -> None:
        super().__init__(message)
        self.total = total


@dataclass(frozen=True)
class MediaResponse:
    """What to send back for a media request: stream `body` with these headers."""

    status: int  # 200 (whole file) or 206 (a range)
    content_type: str
    content_length: int
    content_range: str | None  # "bytes start-end/total" for a 206
    body: Iterator[bytes]


@dataclass
class _Formats:
    by_id: dict[str, Format]  # adaptive https streams only
    fresh_until: datetime


@dataclass
class _CachedVideo:
    video: Video
    fresh_until: datetime


@dataclass
class _CachedSegments:
    segments: list[SponsorSegment]
    fresh_until: datetime


class Playback:
    """Manifests and the media proxy for one process, with in-memory caches.

    Thread-safe: the API serves media requests from a thread pool.
    """

    def __init__(
        self,
        gateway: Gateway,
        *,
        sponsorblock: SponsorBlock | None = None,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        chunk_bytes: int = MAX_RANGE_BYTES,
    ) -> None:
        if not 0 < chunk_bytes <= MAX_RANGE_BYTES:
            raise ValueError(f"chunk_bytes must be 1 to {MAX_RANGE_BYTES}")
        self._gateway = gateway
        self._sponsorblock = sponsorblock or HttpSponsorBlock()
        self._segments: OrderedDict[str, _CachedSegments] = OrderedDict()
        self._now = now
        self._chunk_bytes = chunk_bytes
        self._lock = threading.Lock()
        self._video_locks: dict[str, threading.Lock] = {}
        self._videos: OrderedDict[str, _CachedVideo] = OrderedDict()
        self._formats: OrderedDict[str, _Formats] = OrderedDict()
        # Probed (init, index) ranges, per file: (video id, format id, lmt or clen).
        self._probed: dict[tuple[str, str, str], tuple[ByteRange, ByteRange] | None] = {}

    # Metadata

    def video(self, video_id: str) -> Video:
        """The video's metadata from the Gateway, cached for `VIDEO_TTL`."""
        with self._video_lock(video_id):
            with self._lock:
                cached = self._videos.get(video_id)
                if cached is not None and cached.fresh_until > self._now():
                    self._videos.move_to_end(video_id)
                    return cached.video
            video = self._gateway.get_video(video_id)
            with self._lock:
                self._videos[video_id] = _CachedVideo(video, self._now() + VIDEO_TTL)
                _trim(self._videos)
            return video

    # SponsorBlock

    def sponsor_segments(self, video_id: str) -> list[SponsorSegment]:
        """The video's SponsorBlock segments to skip, by start time, cached for
        `SEGMENTS_TTL`. Raises `SponsorBlockError` when SponsorBlock can't be asked
        (failures aren't cached)."""
        with self._lock:
            cached = self._segments.get(video_id)
            if cached is not None and cached.fresh_until > self._now():
                self._segments.move_to_end(video_id)
                return list(cached.segments)
        segments = self._sponsorblock.skip_segments(video_id)
        with self._lock:
            self._segments[video_id] = _CachedSegments(segments, self._now() + SEGMENTS_TTL)
            _trim(self._segments)
        return list(segments)

    # Manifest

    def manifest(self, video_id: str) -> str:
        """A static DASH MPD (SegmentBase) of the video's adaptive streams.

        Raises `NoPlayableStreamsError` when there are none, and Gateway errors.
        """
        video = self.video(video_id)
        streams = self._manifest_streams(video_id)
        if not any(f.kind == "video" for f in streams) or not any(
            f.kind == "audio" for f in streams
        ):
            raise NoPlayableStreamsError(f"No playable streams for {video_id}")
        return build_mpd(video, streams)

    def _manifest_streams(self, video_id: str) -> list[Format]:
        formats = select_streams(list(self._formats_for(video_id).values()))
        missing = [f for f in formats if f.init_range is None or f.index_range is None]
        if not missing:
            return formats
        with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
            probed = dict(
                zip(
                    (f.itag for f in missing),
                    pool.map(lambda f: self._probe(video_id, f), missing),
                    strict=True,
                )
            )
        streams: list[Format] = []
        for fmt in formats:
            if fmt.itag not in probed:
                streams.append(fmt)
            elif (ranges := probed[fmt.itag]) is not None:
                streams.append(replace(fmt, init_range=ranges[0], index_range=ranges[1]))
        return streams

    def _probe(self, video_id: str, fmt: Format) -> tuple[ByteRange, ByteRange] | None:
        """Ranges by reading the file's start; None (leave the stream out) on failure."""
        key = (video_id, fmt.itag, _file_identity(fmt))
        with self._lock:
            if key in self._probed:
                return self._probed[key]
        try:
            ranges = self._gateway.probe_dash_ranges(fmt)
        except GatewayError:
            return None  # don't cache: the next manifest may get a working URL
        with self._lock:
            self._probed[key] = ranges
        return ranges

    # Media proxy

    def proxy_range(self, video_id: str, format_id: str, range_header: str | None) -> MediaResponse:
        """Serve `range_header` (`bytes=a-b`, `bytes=a-` or `bytes=-n`) of one stream.

        Without a usable Range header the whole file is served (200). Upstream reads are
        always ranged and at most `MAX_RANGE_BYTES` each, chained for longer requests.
        Errors before the first byte raise: `StreamNotFoundError`, `RangeNotSatisfiable`,
        `StreamChangedError` and Gateway errors. The first read happens here, so an
        expired URL is refreshed before any response is started.
        """
        fmt = self._stream(video_id, format_id)
        total = fmt.filesize or _clen(fmt)
        requested = _parse_range(range_header)
        if requested is None:
            start, end = 0, None
        else:
            start, end = requested
            if start is None:  # suffix: the last `end` bytes
                if total is None or end is None or end == 0:
                    raise RangeNotSatisfiable(f"Unsupported range {range_header!r}", total)
                start, end = max(total - end, 0), None
        if total is not None:
            if start >= total:
                raise RangeNotSatisfiable(f"{range_header!r} is past the end", total)
            end = total - 1 if end is None else min(end, total - 1)

        first = self._open(video_id, format_id, self._chunk(start, end))
        total = total or first.total
        if total is None:
            first.close()
            raise RangeNotSatisfiable("The stream's size is unknown", None)
        end = total - 1 if end is None else min(end, total - 1)
        length = end - start + 1
        return MediaResponse(
            status=206 if requested is not None else 200,
            content_type=fmt.mime_type,
            content_length=length,
            content_range=f"bytes {start}-{end}/{total}" if requested is not None else None,
            body=self._body(video_id, format_id, first, end),
        )

    def _chunk(self, start: int, end: int | None) -> ByteRange:
        last = start + self._chunk_bytes - 1
        return ByteRange(start, last if end is None else min(end, last))

    def _body(self, video_id: str, format_id: str, first: MediaStream, end: int) -> Iterator[bytes]:
        stream = first
        try:
            while True:
                yield from stream
                position = stream.byte_range.end + 1
                if position > end:
                    return
                stream = self._open(video_id, format_id, self._chunk(position, end))
        finally:
            stream.close()

    def _open(self, video_id: str, format_id: str, byte_range: ByteRange) -> MediaStream:
        fmt = self._stream(video_id, format_id)
        try:
            return self._gateway.open_media(fmt, byte_range)
        except MediaUrlExpiredError:
            fmt = self._stream(video_id, format_id, refused=fmt)
            return self._gateway.open_media(fmt, byte_range)
        except RangeNotSatisfiableError as error:
            raise RangeNotSatisfiable(str(error), fmt.filesize or _clen(fmt)) from error

    def _stream(self, video_id: str, format_id: str, *, refused: Format | None = None) -> Format:
        """The stream's current format, re-resolved if expiring or `refused` upstream."""
        formats = self._formats_for(video_id, refused=refused)
        fmt = formats.get(format_id)
        if fmt is None:
            raise StreamNotFoundError(f"Video {video_id} has no stream {format_id!r}")
        if refused is not None and _file_identity(fmt) != _file_identity(refused):
            raise StreamChangedError(f"Stream {format_id} of {video_id} changed; reload")
        return fmt

    def _formats_for(self, video_id: str, *, refused: Format | None = None) -> dict[str, Format]:
        with self._video_lock(video_id):
            with self._lock:
                cached = self._formats.get(video_id)
            stale = cached is None or cached.fresh_until <= self._now()
            if cached is not None and refused is not None:
                current = cached.by_id.get(refused.itag)
                # Another request may have refreshed already; refresh only once per URL.
                stale = stale or current is None or current.url == refused.url
            if not stale and cached is not None:
                with self._lock:
                    self._formats.move_to_end(video_id)
                return cached.by_id
            previous = cached.by_id if cached is not None else {}
            by_id = _adaptive_streams(self._gateway.get_formats(video_id))
            for format_id, old in previous.items():
                new = by_id.get(format_id)
                if new is not None and _file_identity(new) != _file_identity(old):
                    # The file changed under an open manifest: drop its probed ranges.
                    with self._lock:
                        self._probed.pop((video_id, format_id, _file_identity(old)), None)
            entry = _Formats(by_id, self._fresh_until(by_id.values()))
            with self._lock:
                self._formats[video_id] = entry
                _trim(self._formats)
            return by_id

    def _fresh_until(self, formats: Iterable[Format]) -> datetime:
        now = self._now()
        expiries = [f.expires_at for f in formats if f.expires_at is not None]
        if not expiries:
            return now + FORMATS_TTL
        # URLs that come back already close to expiry are used for a minute anyway
        # (a refused one is still refreshed), rather than re-extracted on every read.
        return max(min(expiries) - URL_REFRESH_MARGIN, now + MIN_FORMATS_TTL)

    def _video_lock(self, video_id: str) -> threading.Lock:
        with self._lock:
            lock = self._video_locks.get(video_id)
            if lock is None:
                if len(self._video_locks) > CACHED_VIDEOS * 4:
                    self._video_locks.clear()  # only ever a cache of locks
                lock = self._video_locks[video_id] = threading.Lock()
            return lock


# Stream selection and the MPD


def select_streams(formats: list[Format]) -> list[Format]:
    """The adaptive streams to offer the player.

    Drops DRC audio (a quieter duplicate of each track) and dubbed audio: only the
    original-language track is kept (yt-dlp notes it "original" or "default"). Every
    codec family is kept, so the player picks what the browser supports: mp4 (avc1,
    av01, AAC) is always there for Safari, webm (vp9, Opus) elsewhere.
    """
    streams = [f for f in formats if _is_adaptive(f) and not f.is_drc]
    audio = [f for f in streams if f.kind == "audio"]
    languages = {f.language for f in audio}
    if len(languages) > 1:
        for marker in ("original", "default"):
            preferred = {f.language for f in audio if marker in (f.note or "").lower()}
            if len(preferred) == 1:
                break
        else:
            # No hint: keep the language with the most tracks (the others are dubs).
            counts = {lang: sum(f.language == lang for f in audio) for lang in languages}
            preferred = {max(counts, key=lambda lang: counts[lang] or 0)}
        streams = [f for f in streams if f.kind != "audio" or f.language in preferred]
    return streams


def build_mpd(video: Video, streams: list[Format]) -> str:
    """A static, on-demand profile MPD with one SegmentBase Representation per stream.

    Streams without both byte ranges are left out. AdaptationSets group streams by
    kind, container and codec family, so the player never switches codecs mid-play.
    """
    mpd = ET.Element(
        "MPD",
        {
            "xmlns": _MPD_NS,
            "profiles": "urn:mpeg:dash:profile:isoff-on-demand:2011",
            "type": "static",
            "minBufferTime": "PT2S",
        },
    )
    if video.duration_seconds:
        mpd.set("mediaPresentationDuration", f"PT{video.duration_seconds}S")
    period = ET.SubElement(mpd, "Period", {"id": "0", "start": "PT0S"})

    groups: dict[tuple[str, str, str, str], list[Format]] = {}
    for fmt in streams:
        if fmt.init_range is None or fmt.index_range is None:
            continue
        key = (fmt.kind, fmt.mime_type, _codec_family(fmt.codecs), fmt.language or "")
        groups.setdefault(key, []).append(fmt)

    order = {"video": 0, "audio": 1}
    for set_id, (key, members) in enumerate(
        sorted(groups.items(), key=lambda item: (order.get(item[0][0], 2), item[0][1:]))
    ):
        kind, mime_type, _, language = key
        attributes = {
            "id": str(set_id),
            "contentType": kind,
            "mimeType": mime_type,
            "subsegmentAlignment": "true",
            "subsegmentStartsWithSAP": "1",
        }
        if language:
            attributes["lang"] = language
        adaptation = ET.SubElement(period, "AdaptationSet", attributes)
        if kind == "audio":
            ET.SubElement(adaptation, "Role", {"schemeIdUri": _ROLE_SCHEME, "value": "main"})
        for fmt in sorted(members, key=lambda f: _bandwidth(f, video)):
            _representation(adaptation, fmt, video)

    body = ET.tostring(mpd, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"


def _representation(adaptation: ET.Element, fmt: Format, video: Video) -> None:
    assert fmt.init_range is not None and fmt.index_range is not None
    attributes = {
        "id": fmt.itag,
        "codecs": fmt.codecs,
        "bandwidth": str(_bandwidth(fmt, video)),
    }
    if fmt.kind == "video":
        if fmt.width and fmt.height:
            attributes |= {"width": str(fmt.width), "height": str(fmt.height)}
        if fmt.fps:
            attributes["frameRate"] = f"{fmt.fps:g}"
    elif fmt.audio_sample_rate:
        attributes["audioSamplingRate"] = str(fmt.audio_sample_rate)
    representation = ET.SubElement(adaptation, "Representation", attributes)
    if fmt.kind == "audio" and fmt.audio_channels:
        ET.SubElement(
            representation,
            "AudioChannelConfiguration",
            {"schemeIdUri": _AUDIO_CHANNELS_SCHEME, "value": str(fmt.audio_channels)},
        )
    ET.SubElement(representation, "BaseURL").text = f"media/{fmt.itag}"
    segment_base = ET.SubElement(
        representation, "SegmentBase", {"indexRange": str(fmt.index_range)}
    )
    ET.SubElement(segment_base, "Initialization", {"range": str(fmt.init_range)})


def _bandwidth(fmt: Format, video: Video) -> int:
    if fmt.bitrate:
        return fmt.bitrate
    size = fmt.filesize or _clen(fmt)
    if size and video.duration_seconds:
        return round(size * 8 / video.duration_seconds)
    return 1


def _codec_family(codecs: str) -> str:
    family = codecs.split(".")[0].lower()
    return {"vp09": "vp9"}.get(family, family)


def _is_adaptive(fmt: Format) -> bool:
    return fmt.protocol == "https" and fmt.kind in ("video", "audio")


def _adaptive_streams(formats: list[Format]) -> dict[str, Format]:
    by_id: dict[str, Format] = {}
    for fmt in formats:
        if _is_adaptive(fmt):
            by_id.setdefault(fmt.itag, fmt)
    return by_id


def _url_param(fmt: Format, name: str) -> str | None:
    values = parse_qs(urlsplit(fmt.url).query).get(name)
    return values[0] if values else None


def _clen(fmt: Format) -> int | None:
    value = _url_param(fmt, "clen")
    return int(value) if value and value.isdigit() else None


def _file_identity(fmt: Format) -> str:
    """Which file a stream URL serves: its last-modified time, else its length."""
    lmt = _url_param(fmt, "lmt")
    if lmt:
        return f"lmt={lmt}"
    size = fmt.filesize or _clen(fmt)
    return f"clen={size}" if size else ""


def _parse_range(header: str | None) -> tuple[int | None, int | None] | None:
    """(start, end) of a single `bytes=` range; start None means a suffix length.

    None when there is no header or it isn't a single byte range (multiple ranges are
    ignored, as RFC 9110 allows, and the whole file is served).
    """
    if not header:
        return None
    match = _RANGE.match(header.strip().replace(" ", ""))
    if match is None:
        return None
    first, last = match.groups()
    if not first and not last:
        return None
    if not first:
        return None, int(last)
    start, end = int(first), int(last) if last else None
    if end is not None and end < start:
        return None
    return start, end


def _trim[V](cache: OrderedDict[str, V]) -> None:
    while len(cache) > CACHED_VIDEOS:
        cache.popitem(last=False)
