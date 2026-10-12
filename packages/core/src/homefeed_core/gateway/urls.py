"""Offline parsing of YouTube URLs. No network: this only reads the URL's shape."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from homefeed_core.gateway.errors import UnsupportedUrlError
from homefeed_core.gateway.models import ResolvedPlaylist, ResolvedVideo

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_HANDLE = re.compile(r"^@[\w.\-·]{1,100}$")
_PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]{10,}$")
_DURATION = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$")

_YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com"}
_VIDEO_PATH_PREFIXES = ("shorts", "embed", "live", "v", "e")
_CHANNEL_TABS = {
    "featured",
    "videos",
    "shorts",
    "streams",
    "playlists",
    "community",
    "about",
    "podcasts",
    "releases",
}


@dataclass(frozen=True)
class ChannelRef:
    """A channel URL whose canonical id may still need a lookup.

    `channel_id` is set only when the URL already contains it (`/channel/UC...`).
    `url` is the canonical channel page to fetch.
    """

    url: str
    channel_id: str | None = None


ParsedUrl = ResolvedVideo | ResolvedPlaylist | ChannelRef


def channel_url(channel_id: str) -> str:
    return f"https://www.youtube.com/channel/{channel_id}"


def video_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def parse_youtube_url(raw: str) -> ParsedUrl:
    """Classify a YouTube URL. Raises `UnsupportedUrlError` for anything unrecognized."""
    text = raw.strip()
    if _HANDLE.match(text):
        return ChannelRef(url=f"https://www.youtube.com/{text}")
    if "://" not in text:
        text = f"https://{text}"
    parts = urlsplit(text)
    host = (parts.hostname or "").lower().removeprefix("www.")
    query = parse_qs(parts.query)
    segments = [s for s in parts.path.split("/") if s]

    if host == "youtu.be":
        if segments and VIDEO_ID.match(segments[0]):
            return ResolvedVideo(segments[0], _start_seconds(query))
        raise UnsupportedUrlError(f"Not a video link: {raw!r}")
    if host not in _YOUTUBE_HOSTS:
        raise UnsupportedUrlError(f"Not a YouTube URL: {raw!r}")

    first = segments[0] if segments else ""
    if first == "watch":
        video_id = _first(query, "v")
        if video_id and VIDEO_ID.match(video_id):
            return ResolvedVideo(video_id, _start_seconds(query))
    elif first in _VIDEO_PATH_PREFIXES and len(segments) >= 2 and VIDEO_ID.match(segments[1]):
        return ResolvedVideo(segments[1], _start_seconds(query), is_short_url=first == "shorts")
    elif first == "playlist":
        playlist_id = _first(query, "list")
        if playlist_id and _PLAYLIST_ID.match(playlist_id):
            return ResolvedPlaylist(playlist_id)
    elif first == "channel" and len(segments) >= 2 and CHANNEL_ID.match(segments[1]):
        return ChannelRef(url=channel_url(segments[1]), channel_id=segments[1])
    elif first in ("c", "user") and len(segments) >= 2 and _is_channel_tail(segments[2:]):
        return ChannelRef(url=f"https://www.youtube.com/{first}/{segments[1]}")
    elif _HANDLE.match(first) and _is_channel_tail(segments[1:]):
        return ChannelRef(url=f"https://www.youtube.com/{first}")
    raise UnsupportedUrlError(f"Unrecognized YouTube URL: {raw!r}")


def _is_channel_tail(rest: list[str]) -> bool:
    return not rest or (len(rest) == 1 and rest[0] in _CHANNEL_TABS)


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _start_seconds(query: dict[str, list[str]]) -> int | None:
    """Parse `t=90`, `t=90s`, `t=1m30s` or `start=90`."""
    value = _first(query, "t") or _first(query, "start")
    if not value:
        return None
    match = _DURATION.match(value)
    if match is None or not any(match.groups()):
        return None
    hours, minutes, seconds = (int(g) if g else 0 for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds
