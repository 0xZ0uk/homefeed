"""Turn raw extractor info dicts (yt-dlp's JSON shape) into domain dataclasses.

Pure functions over plain dicts, so they are tested against recorded responses.
"""

from collections.abc import Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

from homefeed_core.gateway.errors import ExtractionError
from homefeed_core.gateway.models import (
    ByteRange,
    Captions,
    CaptionSegment,
    Channel,
    ChannelUploads,
    Chapter,
    FeaturedChannel,
    Format,
    FormatKind,
    LiveStatus,
    RelatedVideo,
    SearchResult,
    UploadSummary,
    Video,
)
from homefeed_core.gateway.urls import CHANNEL_ID, VIDEO_ID, channel_url

Info = Mapping[str, Any]

_LIVE_STATUSES: set[str] = {"not_live", "is_live", "is_upcoming", "was_live", "post_live"}
_AUDIO_CONTAINERS = {"m4a": "mp4", "mp4": "mp4", "webm": "webm", "weba": "webm"}


def video_from_info(info: Info) -> Video:
    video_id = _require_str(info, "id")
    return Video(
        id=video_id,
        title=_require_str(info, "title"),
        channel_id=_require_str(info, "channel_id"),
        channel_title=_str(info, "channel") or _str(info, "uploader") or "",
        channel_handle=_handle(info),
        description=_str(info, "description"),
        duration_seconds=_int(info, "duration"),
        published_at=_published_at(info),
        thumbnail_url=_str(info, "thumbnail") or _best_thumbnail(info),
        live_status=_live_status(info) or "not_live",
        is_short=_str(info, "media_type") == "short",
        view_count=_int(info, "view_count"),
        tags=tuple(t for t in _list(info, "tags") if isinstance(t, str)),
        chapters=tuple(_chapters(info)),
    )


def formats_from_info(info: Info) -> list[Format]:
    """Playable formats, skipping storyboards and entries without a URL."""
    formats: list[Format] = []
    for raw in _list(info, "formats"):
        if isinstance(raw, Mapping):
            fmt = _format(cast(Info, raw))
            if fmt is not None:
                formats.append(fmt)
    return formats


# DASH byte ranges. InnerTube's player response has `initRange`/`indexRange` for every
# adaptive stream, but yt-dlp drops them; `ytdlp.py` copies them onto its format dicts
# as `init_range`/`index_range` ({"start": int, "end": int}, inclusive) with these.

type DashRanges = dict[tuple[str, str, str], tuple[dict[str, int], dict[str, int]]]


def dash_ranges(player_responses: Iterable[Any]) -> DashRanges:
    """Index the ranges in raw player responses by (itag, "lmt"|"clen", value).

    One itag can name several files (DRC audio, dubbed tracks, re-encodes) with
    different ranges, so a stream is identified by its last-modified time, or by its
    length when that is unambiguous.
    """
    ranges: DashRanges = {}
    conflicts: set[tuple[str, str, str]] = set()
    for response in player_responses:
        if not isinstance(response, Mapping):
            continue
        streaming = cast(Info, response).get("streamingData")
        if not isinstance(streaming, Mapping):
            continue
        for raw in _list(cast(Info, streaming), "adaptiveFormats"):
            if not isinstance(raw, Mapping):
                continue
            stream = cast(Info, raw)
            init, index = _raw_range(stream, "initRange"), _raw_range(stream, "indexRange")
            if init is None or index is None or stream.get("itag") is None:
                continue
            itag = str(stream["itag"])
            for field_name, raw_key in (("lmt", "lastModified"), ("clen", "contentLength")):
                value = stream.get(raw_key)
                if value is None:
                    continue
                key = (itag, field_name, str(value))
                if ranges.setdefault(key, (init, index)) != (init, index):
                    conflicts.add(key)
    for key in conflicts:
        del ranges[key]
    return ranges


def add_dash_ranges(fmt: MutableMapping[str, Any], ranges: DashRanges) -> None:
    """Set `init_range`/`index_range` on a yt-dlp format dict whose stream is in `ranges`."""
    url, format_id = fmt.get("url"), fmt.get("format_id")
    if not isinstance(url, str) or not isinstance(format_id, str):
        return
    itag = format_id.split("-")[0]
    query = parse_qs(urlsplit(url).query)
    for field_name in ("lmt", "clen"):
        for value in query.get(field_name, []):
            found = ranges.get((itag, field_name, value))
            if found is not None:
                fmt["init_range"], fmt["index_range"] = dict(found[0]), dict(found[1])
                return


def _raw_range(stream: Info, key: str) -> dict[str, int] | None:
    value = stream.get(key)
    if not isinstance(value, Mapping):
        return None
    bounds = cast(Info, value)
    try:
        start, end = int(bounds["start"]), int(bounds["end"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"start": start, "end": end} if 0 <= start <= end else None


def channel_from_info(info: Info) -> Channel:
    """The channel described by a channel page (tab) response."""
    channel_id = _str(info, "channel_id") or _str(info, "id")
    if channel_id is None or not CHANNEL_ID.match(channel_id):
        raise ExtractionError(f"Channel response has no channel id (got {channel_id!r})")
    return Channel(
        id=channel_id,
        title=_str(info, "channel") or _str(info, "uploader") or _str(info, "title") or "",
        handle=_handle(info),
        url=channel_url(channel_id),
        thumbnail_url=_channel_avatar(info),
        description=_str(info, "description"),
        banner_url=_channel_banner(info),
        subscriber_count=_int(info, "channel_follower_count"),
    )


def channel_uploads_from_info(info: Info) -> ChannelUploads:
    uploads: list[UploadSummary] = []
    for raw in _list(info, "entries"):
        if not isinstance(raw, Mapping):
            continue
        entry = cast(Info, raw)
        video_id, title = _str(entry, "id"), _str(entry, "title")
        if video_id is None or title is None:
            continue
        uploads.append(
            UploadSummary(
                id=video_id,
                title=title,
                duration_seconds=_int(entry, "duration"),
                view_count=_int(entry, "view_count"),
                thumbnail_url=_best_thumbnail(entry),
                published_at=_published_at(entry),
                live_status=_live_status(entry),
            )
        )
    return ChannelUploads(channel=channel_from_info(info), videos=uploads)


# Related videos. A related request (see `ytdlp.py`) reads the watch page's related
# list and returns {"id": <seed video id>, "entries": [...]}, one flat yt-dlp entry per
# suggested video (id, title, channel_id, channel, uploader_id, duration, view_count,
# thumbnails, live_status).


def related_from_info(info: Info) -> list[RelatedVideo]:
    """The suggested videos in a related response, in order, without duplicates or the
    seed itself. Entries without a channel id are skipped: they can't be stored."""
    seed = _require_str(info, "id")
    related: list[RelatedVideo] = []
    seen = {seed}
    for raw in _list(info, "entries"):
        if not isinstance(raw, Mapping):
            continue
        entry = cast(Info, raw)
        video_id, title = _str(entry, "id"), _str(entry, "title")
        channel_id = _str(entry, "channel_id")
        if video_id is None or title is None or video_id in seen:
            continue
        if channel_id is None or not CHANNEL_ID.match(channel_id):
            continue
        seen.add(video_id)
        related.append(
            RelatedVideo(
                id=video_id,
                title=title,
                channel_id=channel_id,
                channel_title=_str(entry, "channel") or _str(entry, "uploader") or "",
                channel_handle=_handle(entry),
                duration_seconds=_int(entry, "duration"),
                view_count=_int(entry, "view_count"),
                thumbnail_url=_best_thumbnail(entry),
                live_status=_live_status(entry),
            )
        )
    return related


# Search. A search request (see `ytdlp.search_url`) lists YouTube's results flat:
# {"id": <query>, "entries": [...]}, one yt-dlp entry per video (id, title, description
# snippet, channel_id, channel, uploader_id, duration, view_count, thumbnails,
# live_status). Search results carry no upload time.


def search_results_from_info(info: Info) -> list[SearchResult]:
    """The videos in a search response, in order, without duplicates. Entries without a
    channel id (Shorts shelves, channels, playlists) are skipped."""
    results: list[SearchResult] = []
    seen: set[str] = set()
    for raw in _list(info, "entries"):
        if not isinstance(raw, Mapping):
            continue
        entry = cast(Info, raw)
        video_id, title = _str(entry, "id"), _str(entry, "title")
        channel_id = _str(entry, "channel_id")
        if video_id is None or title is None or video_id in seen:
            continue
        if not VIDEO_ID.match(video_id) or channel_id is None or not CHANNEL_ID.match(channel_id):
            continue
        seen.add(video_id)
        results.append(
            SearchResult(
                id=video_id,
                title=title,
                channel_id=channel_id,
                channel_title=_str(entry, "channel") or _str(entry, "uploader") or "",
                channel_handle=_handle(entry),
                description=_str(entry, "description"),
                duration_seconds=_int(entry, "duration"),
                view_count=_int(entry, "view_count"),
                thumbnail_url=_best_thumbnail(entry),
                live_status=_live_status(entry),
            )
        )
    return results


# Featured channels. A featured request (see `ytdlp.py`) reads the channel's home tab
# and returns {"id": <channel id>, "entries": [...]}, one entry per featured channel
# (id, title, uploader_id, thumbnails, channel_follower_count, video_count).


def featured_channels_from_info(info: Info) -> list[FeaturedChannel]:
    """The featured channels in a featured response, in order, without duplicates or
    the featuring channel itself. Entries without a valid channel id are skipped."""
    owner = _require_str(info, "id")
    featured: list[FeaturedChannel] = []
    seen = {owner}
    for raw in _list(info, "entries"):
        if not isinstance(raw, Mapping):
            continue
        entry = cast(Info, raw)
        channel_id = _str(entry, "id")
        if channel_id is None or not CHANNEL_ID.match(channel_id) or channel_id in seen:
            continue
        seen.add(channel_id)
        featured.append(
            FeaturedChannel(
                id=channel_id,
                title=_str(entry, "title") or "",
                handle=_handle(entry),
                url=channel_url(channel_id),
                thumbnail_url=_best_thumbnail(entry),
                subscriber_count=_int(entry, "channel_follower_count"),
                video_count=_int(entry, "video_count"),
            )
        )
    return featured


# Captions. A captions request (see `ytdlp.py`) picks one track from the video's info
# with `pick_caption_track`, downloads it as json3 and returns
# {"id": ..., "captions": {"language": ..., "automatic": bool, "events": [...]}}, with
# "captions": null when the video has no usable track.


@dataclass(frozen=True)
class CaptionTrack:
    language: str
    is_automatic: bool
    url: str  # the json3 download


def pick_caption_track(info: Info) -> CaptionTrack | None:
    """The track to read a video's transcript from, preferring English.

    Embeddings are English-only, so in order: uploaded English captions, automatic
    captions of English speech (`en-orig`), YouTube's automatic English translation,
    uploaded captions in the video's own language (then any), and finally automatic
    captions in the original language (`xx-orig`). Only tracks offered as json3 count.
    """
    manual = _caption_tracks(info, "subtitles", is_automatic=False)
    automatic = _caption_tracks(info, "automatic_captions", is_automatic=True)
    original = _str(info, "language")

    def manual_english(lang: str) -> bool:
        return lang == "en" or lang.startswith("en-")

    preferences: list[tuple[dict[str, CaptionTrack], Callable[[str], bool]]] = [
        (manual, lambda lang: lang == "en"),
        (manual, manual_english),
        (automatic, lambda lang: lang == "en-orig"),
        (automatic, lambda lang: lang == "en"),
        (manual, lambda lang: original is not None and lang.split("-")[0] == original),
        (manual, lambda _lang: True),
        (automatic, lambda lang: lang.endswith("-orig")),
    ]
    for tracks, wanted in preferences:
        for lang, track in tracks.items():
            if wanted(lang):
                return track
    return None


def _caption_tracks(info: Info, key: str, *, is_automatic: bool) -> dict[str, CaptionTrack]:
    tracks: dict[str, CaptionTrack] = {}
    listing = info.get(key)
    if not isinstance(listing, Mapping):
        return tracks
    for lang, formats in cast(Info, listing).items():
        if lang == "live_chat" or not isinstance(formats, list):
            continue
        for raw in cast(list[Any], formats):
            if isinstance(raw, Mapping) and raw.get("ext") == "json3":
                url = _str(cast(Info, raw), "url")
                if url is not None:
                    tracks[lang] = CaptionTrack(lang, is_automatic, url)
                    break
    return tracks


def captions_from_info(info: Info) -> Captions | None:
    """The captions in a captions response, or None when the video has none."""
    video_id = _require_str(info, "id")
    raw = info.get("captions")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ExtractionError("Captions response has a malformed 'captions' entry")
    track = cast(Info, raw)
    segments: list[CaptionSegment] = []
    for event in _list(track, "events"):
        if isinstance(event, Mapping):
            segment = _caption_segment(cast(Info, event))
            if segment is not None:
                segments.append(segment)
    return Captions(
        video_id=video_id,
        language=_require_str(track, "language"),
        is_automatic=track.get("automatic") is True,
        segments=tuple(segments),
    )


def _caption_segment(event: Info) -> CaptionSegment | None:
    """One json3 event: `tStartMs`, `dDurationMs` and text pieces in `segs`.

    Automatic captions split lines into word-level pieces and add newline-only events
    between lines; those (and styling-only events without `segs`) are skipped.
    """
    start = _int(event, "tStartMs")
    if start is None:
        return None
    pieces = [
        _str(cast(Info, seg), "utf8") or ""
        for seg in _list(event, "segs")
        if isinstance(seg, Mapping)
    ]
    text = " ".join("".join(pieces).split())
    if not text:
        return None
    duration = _int(event, "dDurationMs") or 0
    return CaptionSegment(start / 1000, (start + duration) / 1000, text)


def _format(raw: Info) -> Format | None:
    url, itag = _str(raw, "url"), _str(raw, "format_id")
    if url is None or itag is None:
        return None
    if raw.get("protocol") == "mhtml":  # storyboard images
        return None
    vcodec, acodec = _codec(raw, "vcodec"), _codec(raw, "acodec")
    kind: FormatKind
    if vcodec and acodec:
        kind = "muxed"
    elif vcodec:
        kind = "video"
    elif acodec or _codec(raw, "audio_ext"):  # HLS audio omits acodec
        kind = "audio"
    elif _codec(raw, "video_ext"):
        kind = "video"
    else:
        return None
    ext = _str(raw, "ext") or "mp4"
    container = _AUDIO_CONTAINERS.get(ext, ext)
    tbr = raw.get("tbr")
    headers = raw.get("http_headers")
    return Format(
        itag=itag,
        kind=kind,
        url=url,
        protocol=_str(raw, "protocol") or "https",
        mime_type=f"{'audio' if kind == 'audio' else 'video'}/{container}",
        codecs=", ".join(c for c in (vcodec, acodec) if c),
        width=_int(raw, "width"),
        height=_int(raw, "height"),
        fps=_float(raw, "fps"),
        bitrate=round(tbr * 1000) if isinstance(tbr, int | float) and tbr > 0 else None,
        filesize=_int(raw, "filesize") or _int(raw, "filesize_approx"),
        audio_sample_rate=_int(raw, "asr"),
        audio_channels=_int(raw, "audio_channels"),
        language=_str(raw, "language"),
        dynamic_range=_str(raw, "dynamic_range"),
        is_drc=itag.endswith("-drc"),
        note=_str(raw, "format_note"),
        expires_at=_url_expiry(url),
        http_headers=(
            {str(k): str(v) for k, v in cast(Info, headers).items()}
            if isinstance(headers, Mapping)
            else {}
        ),
        init_range=_byte_range(raw, "init_range"),
        index_range=_byte_range(raw, "index_range"),
    )


def _byte_range(raw: Info, key: str) -> ByteRange | None:
    value = raw.get(key)
    if not isinstance(value, Mapping):
        return None
    bounds = cast(Info, value)
    start, end = _int(bounds, "start"), _int(bounds, "end")
    if start is None or end is None or not 0 <= start <= end:
        return None
    return ByteRange(start, end)


def _codec(raw: Info, key: str) -> str | None:
    value = _str(raw, key)
    return None if value in (None, "none") else value


def _url_expiry(url: str) -> datetime | None:
    """googlevideo URLs carry their expiry as `expire=` or a `/expire/<ts>/` path part."""
    parts = urlsplit(url)
    values = parse_qs(parts.query).get("expire")
    if not values:
        segments = parts.path.split("/")
        if "expire" in segments:
            index = segments.index("expire")
            values = segments[index + 1 : index + 2]
    if values and values[0].isdigit():
        return datetime.fromtimestamp(int(values[0]), UTC)
    return None


def _published_at(info: Info) -> datetime | None:
    for key in ("timestamp", "release_timestamp"):
        value = info.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return datetime.fromtimestamp(value, UTC)
    for key in ("upload_date", "release_date"):
        value = _str(info, key)
        if value and len(value) == 8 and value.isdigit():
            return datetime.strptime(value, "%Y%m%d").replace(tzinfo=UTC)
    return None


def _live_status(info: Info) -> LiveStatus | None:
    value = _str(info, "live_status")
    if value in _LIVE_STATUSES:
        return cast(LiveStatus, value)
    if info.get("is_live") is True:
        return "is_live"
    return None


def _handle(info: Info) -> str | None:
    for key in ("uploader_id", "channel_handle"):
        value = _str(info, key)
        if value and value.startswith("@"):
            return value
    return None


def _chapters(info: Info) -> list[Chapter]:
    chapters: list[Chapter] = []
    for raw in _list(info, "chapters"):
        if not isinstance(raw, Mapping):
            continue
        entry = cast(Info, raw)
        start, end = _float(entry, "start_time"), _float(entry, "end_time")
        if start is not None and end is not None:
            chapters.append(Chapter(_str(entry, "title") or "", start, end))
    return chapters


def _best_thumbnail(info: Info) -> str | None:
    best: tuple[int, str] | None = None
    for raw in _list(info, "thumbnails"):
        if not isinstance(raw, Mapping):
            continue
        thumb = cast(Info, raw)
        url = _str(thumb, "url")
        if url is None:
            continue
        area = (_int(thumb, "width") or 0) * (_int(thumb, "height") or 0)
        if best is None or area >= best[0]:
            best = (area, url)
    return best[1] if best else None


def _channel_avatar(info: Info) -> str | None:
    for raw in _list(info, "thumbnails"):
        if isinstance(raw, Mapping):
            thumb = cast(Info, raw)
            if _str(thumb, "id") == "avatar_uncropped":
                return _str(thumb, "url")
    return None


def _channel_banner(info: Info) -> str | None:
    """The `banner_uncropped` thumbnail, else the widest one whose id starts with
    "banner"."""
    banners: list[Info] = []
    for raw in _list(info, "thumbnails"):
        if isinstance(raw, Mapping):
            thumb = cast(Info, raw)
            thumb_id = _str(thumb, "id") or ""
            if thumb_id == "banner_uncropped":
                return _str(thumb, "url")
            if thumb_id.startswith("banner") and _str(thumb, "url"):
                banners.append(thumb)
    if not banners:
        return None
    return _str(max(banners, key=lambda thumb: _int(thumb, "width") or 0), "url")


def _require_str(info: Info, key: str) -> str:
    value = _str(info, key)
    if value is None:
        raise ExtractionError(f"Extractor response is missing {key!r}")
    return value


def _str(info: Info, key: str) -> str | None:
    value = info.get(key)
    return value if isinstance(value, str) and value else None


def _int(info: Info, key: str) -> int | None:
    value = info.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def _float(info: Info, key: str) -> float | None:
    value = info.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _list(info: Info, key: str) -> list[Any]:
    value = info.get(key)
    return cast(list[Any], value) if isinstance(value, list) else []
