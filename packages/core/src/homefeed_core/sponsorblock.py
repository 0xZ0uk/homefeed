"""SponsorBlock (sponsor.ajay.app): crowd-sourced segments of videos worth skipping.

Only the segments to skip are asked for ("skip" action), in the categories of the
`sponsorblock_categories` user setting (see homefeed_core.user_settings; its default is
`SPONSORBLOCK_CATEGORIES`). Lookups use SponsorBlock's privacy-preserving endpoint: the
request carries the first characters of the video id's SHA-256, never the id, and the
segments of the matching video are picked out of the reply.

    client = HttpSponsorBlock()
    client.skip_segments("dQw4w9WgXcQ")  # -> [SponsorSegment(...), ...], by start time

SponsorBlock isn't YouTube, so this lives outside the Gateway. `Playback` caches it.
"""

import hashlib
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from http.client import HTTPResponse
from typing import Any, Protocol, cast
from urllib.parse import quote, urlencode

from homefeed_core.config import get_settings

DEFAULT_BASE_URL = "https://sponsor.ajay.app"
# Paid promotion, unpaid self-promotion and "like and subscribe" reminders.
DEFAULT_CATEGORIES = ("sponsor", "selfpromo", "interaction")
# Every category SponsorBlock has segments to skip in.
CATEGORIES = frozenset(
    {
        "sponsor",
        "selfpromo",
        "interaction",
        "intro",
        "outro",
        "preview",
        "hook",
        "music_offtopic",
        "filler",
    }
)
HASH_PREFIX_LENGTH = 4
TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_USER_AGENT = "homefeed/0.1 (personal feed reader)"


class SponsorBlockError(Exception):
    """SponsorBlock couldn't be reached or answered with something unreadable."""


@dataclass(frozen=True)
class SponsorSegment:
    id: str  # SponsorBlock's UUID
    category: str  # e.g. "sponsor", see `CATEGORIES`
    start_seconds: float
    end_seconds: float


class SponsorBlock(Protocol):
    def skip_segments(self, video_id: str) -> list[SponsorSegment]:
        """The video's segments to skip, by start time; empty when it has none.

        Raises `SponsorBlockError` when SponsorBlock can't be asked.
        """
        ...


OpenUrl = Callable[[urllib.request.Request, float], HTTPResponse]


def _urlopen(request: urllib.request.Request, timeout: float) -> HTTPResponse:
    return urllib.request.urlopen(request, timeout=timeout)


class HttpSponsorBlock:
    """`SponsorBlock` over its HTTP API. `categories` may be a function, read on each
    lookup. `open_url` is the seam for tests."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        categories: Iterable[str] | Callable[[], Iterable[str]] = DEFAULT_CATEGORIES,
        open_url: OpenUrl = _urlopen,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._categories = categories if callable(categories) else _known(categories)
        self._open_url = open_url
        self._timeout = timeout

    def skip_segments(self, video_id: str) -> list[SponsorSegment]:
        categories = _known(self._categories()) if callable(self._categories) else self._categories
        if not categories:
            return []
        url = skip_segments_url(self._base_url, video_id, categories)
        request = urllib.request.Request(
            url, headers={"User-Agent": _USER_AGENT, "Accept": "application/json"}
        )
        try:
            with self._open_url(request, self._timeout) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            if error.code == 404:  # no video with this hash prefix has segments
                return []
            raise SponsorBlockError(f"SponsorBlock answered HTTP {error.code}") from error
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise SponsorBlockError(f"Could not reach SponsorBlock: {error}") from error
        if len(body) > MAX_RESPONSE_BYTES:
            raise SponsorBlockError("SponsorBlock's response is too large")
        try:
            data = json.loads(body)
        except ValueError as error:
            raise SponsorBlockError("SponsorBlock's response isn't JSON") from error
        return segments_from_response(data, video_id, categories)


def _known(categories: Iterable[str]) -> tuple[str, ...]:
    known = tuple(dict.fromkeys(categories))
    unknown = set(known) - CATEGORIES
    if unknown:
        raise ValueError(f"Unknown SponsorBlock categories: {', '.join(sorted(unknown))}")
    return known


def create_sponsorblock() -> SponsorBlock:
    """The production client: `SPONSORBLOCK_URL`, and the categories of the user
    settings, read on each lookup (empty turns skipping off)."""
    # homefeed_core.user_settings imports this module (for `CATEGORIES`).
    from homefeed_core.user_settings import load_user_settings

    return HttpSponsorBlock(
        base_url=get_settings().sponsorblock_url,
        categories=lambda: load_user_settings().sponsorblock_categories,
    )


def skip_segments_url(base_url: str, video_id: str, categories: Iterable[str]) -> str:
    """The privacy-preserving lookup: by a prefix of the id's SHA-256, not the id."""
    prefix = hashlib.sha256(video_id.encode()).hexdigest()[:HASH_PREFIX_LENGTH]
    query = urlencode(
        {
            "categories": json.dumps(list(categories), separators=(",", ":")),
            "actionTypes": json.dumps(["skip"], separators=(",", ":")),
        },
        quote_via=quote,
    )
    return f"{base_url}/api/skipSegments/{prefix}?{query}"


def segments_from_response(
    data: Any, video_id: str, categories: Iterable[str]
) -> list[SponsorSegment]:
    """The segments of `video_id` in a hash-prefix response, by start time.

    The response lists every video matching the prefix:
    `[{"videoID": ..., "segments": [{"UUID", "category", "actionType", "segment":
    [start, end]}, ...]}, ...]`. Segments in other categories, with another action or
    with an unusable time range are skipped.
    """
    if not isinstance(data, list):
        raise SponsorBlockError("SponsorBlock's response isn't a list")
    wanted = set(categories)
    segments: list[SponsorSegment] = []
    seen: set[str] = set()
    for raw_video in cast(list[Any], data):
        if not isinstance(raw_video, Mapping):
            continue
        video = cast(Mapping[str, Any], raw_video)
        if video.get("videoID") != video_id or not isinstance(video.get("segments"), list):
            continue
        for raw in cast(list[Any], video["segments"]):
            segment = _segment(raw)
            if segment is None or segment.category not in wanted or segment.id in seen:
                continue
            seen.add(segment.id)
            segments.append(segment)
    return sorted(segments, key=lambda s: (s.start_seconds, s.end_seconds))


def _segment(raw: Any) -> SponsorSegment | None:
    if not isinstance(raw, Mapping):
        return None
    entry = cast(Mapping[str, Any], raw)
    times = entry.get("segment")
    uuid, category = entry.get("UUID"), entry.get("category")
    if entry.get("actionType", "skip") != "skip":
        return None
    if not isinstance(uuid, str) or not isinstance(category, str):
        return None
    if not isinstance(times, list) or len(cast(list[Any], times)) != 2:
        return None
    start, end = cast(list[Any], times)
    if not all(isinstance(t, int | float) and not isinstance(t, bool) for t in (start, end)):
        return None
    if start < 0 or end <= start:
        return None
    return SponsorSegment(uuid, category, float(start), float(end))
