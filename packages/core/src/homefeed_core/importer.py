"""Google Takeout import: seed channels and candidates from a YouTube watch history.

`import_takeout` reads a Takeout `watch-history.json` or `watch-history.html` (the format
is detected from the content) and:
- stores each watched video's channel in `channels` and the video in `videos` (stored
  ones keep their metadata; the enricher fetches the rest later),
- records the `max_candidates` most recently watched videos in the candidate pool as
  source `takeout` (rated videos excluded), so they can surface in a feed and be rated,
- optionally subscribes (neutral prior) to channels watched at least
  `subscribe_min_watches` times; existing subscriptions keep their preferences.

It never creates ratings or watch events: a watch elsewhere says nothing about how good
the video was, and ratings stay explicit.

Each history entry is counted in exactly one bucket of the `ImportReport`:
- watches: a watched video with its channel, imported;
- removed: a watch of a video that has since been removed or made private (Takeout
  then gives no link, or a link without the channel), which can't be imported;
- malformed: an entry that doesn't have the expected shape;
- skipped: other activity in the file, e.g. ads ("From Google Ads") or searches.

All URLs are parsed offline with the Gateway's URL parser; nothing is fetched.
"""

import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from html.parser import HTMLParser
from typing import IO, Any, Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from homefeed_core.candidates import record
from homefeed_core.gateway.errors import UnsupportedUrlError
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.gateway.models import ResolvedVideo
from homefeed_core.gateway.urls import ChannelRef, parse_youtube_url

# Candidate source of imported watch history; source_detail is unused (None).
TAKEOUT = "takeout"

DEFAULT_MAX_CANDIDATES = 200
# Upper bound the API accepts for an upload; Takeout histories of heavy users run to
# tens of megabytes.
MAX_TAKEOUT_BYTES = 256 * 1024 * 1024

TakeoutFormat = Literal["json", "html"]

# English Takeout titles; other locales still import (they link the video) but their
# removed-video entries count as skipped rather than removed.
_WATCHED_PREFIX = "Watched "
_ADS_DETAIL = "From Google Ads"


class TakeoutFormatError(ValueError):
    """The file as a whole isn't a Takeout watch history (JSON or HTML)."""


@dataclass(frozen=True)
class ImportReport:
    format: TakeoutFormat
    entries: int  # history entries in the file: watches + removed + malformed + skipped
    watches: int  # watch entries imported (a video with its channel)
    removed: int  # watches of removed or private videos, not importable
    malformed: int  # entries without the expected shape
    skipped: int  # other activity, e.g. ads and searches
    videos: int  # distinct videos among the watches
    channels: int  # distinct channels among the watches
    new_videos: int  # videos stored for the first time
    new_channels: int  # channels stored for the first time
    new_candidates: int  # videos new to the candidate pool
    subscribed: list[str]  # channel ids newly subscribed, most watched first
    oldest_watch_at: str | None  # ISO 8601 UTC, None when no watch had a readable time
    newest_watch_at: str | None


@dataclass(frozen=True)
class _Entry:
    """A history entry as read from the file, before classification."""

    title: str  # e.g. "Watched How rockets work"
    video_url: str | None
    channel_url: str | None
    channel_title: str | None
    watched_at: datetime | None
    is_ad: bool


@dataclass(frozen=True)
class _Watch:
    video_id: str
    title: str
    channel_id: str
    channel_title: str
    watched_at: datetime | None


class _Malformed(Exception):
    pass


class _Removed(Exception):
    pass


class _Skipped(Exception):
    pass


@dataclass
class _ParsedHistory:
    format: TakeoutFormat
    watches: list[_Watch]
    removed: int = 0
    malformed: int = 0
    skipped: int = 0


def import_takeout(
    session: Session,
    file: bytes | str | IO[bytes],
    *,
    subscribe_min_watches: int | None = None,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    now: datetime | None = None,
) -> ImportReport:
    """Import a Takeout watch history (JSON or HTML). The caller commits.

    `subscribe_min_watches` (None: subscribe to nothing) subscribes to channels with at
    least that many watches. Raises `TakeoutFormatError` if the file isn't a watch
    history at all; individual bad entries are counted instead.
    """
    if subscribe_min_watches is not None and subscribe_min_watches < 1:
        raise ValueError("subscribe_min_watches must be at least 1")
    if max_candidates < 0:
        raise ValueError("max_candidates must not be negative")
    parsed = _parse_takeout(file)
    watches = parsed.watches

    channel_titles: dict[str, str] = {}
    video_info: dict[str, _Watch] = {}
    for watch in watches:  # newest first per Takeout order; keep the newest title
        channel_titles.setdefault(watch.channel_id, watch.channel_title)
        video_info.setdefault(watch.video_id, watch)

    new_channels = sum(
        _insert_returning(
            session,
            "INSERT INTO channels (id, title) VALUES (:id, :title) "
            "ON CONFLICT (id) DO NOTHING RETURNING id",
            {"id": channel_id, "title": title},
        )
        for channel_id, title in channel_titles.items()
    )
    new_videos = sum(
        _insert_returning(
            session,
            "INSERT INTO videos (id, channel_id, title) VALUES (:id, :channel_id, :title) "
            "ON CONFLICT (id) DO NOTHING RETURNING id",
            {"id": watch.video_id, "channel_id": watch.channel_id, "title": watch.title},
        )
        for watch in video_info.values()
    )

    rated = set(session.execute(text("SELECT video_id FROM ratings")).scalars())
    recent = [watch.video_id for watch in _newest_first(watches) if watch.video_id not in rated]
    to_record = list(dict.fromkeys(recent))[:max_candidates]
    new_candidates = record(session, to_record, source=TAKEOUT, now=now)

    subscribed: list[str] = []
    if subscribe_min_watches is not None:
        counts = Counter(watch.channel_id for watch in watches)
        for channel_id, count in counts.most_common():
            if count < subscribe_min_watches:
                break
            if _insert_returning(
                session,
                "INSERT INTO channel_prefs (channel_id) VALUES (:id) "
                "ON CONFLICT (channel_id) DO NOTHING RETURNING channel_id",
                {"id": channel_id},
            ):
                subscribed.append(channel_id)

    times = [watch.watched_at for watch in watches if watch.watched_at is not None]
    return ImportReport(
        format=parsed.format,
        entries=len(watches) + parsed.removed + parsed.malformed + parsed.skipped,
        watches=len(watches),
        removed=parsed.removed,
        malformed=parsed.malformed,
        skipped=parsed.skipped,
        videos=len(video_info),
        channels=len(channel_titles),
        new_videos=new_videos,
        new_channels=new_channels,
        new_candidates=len(new_candidates),
        subscribed=subscribed,
        oldest_watch_at=format_timestamp(min(times)) if times else None,
        newest_watch_at=format_timestamp(max(times)) if times else None,
    )


def _parse_takeout(file: bytes | str | IO[bytes]) -> _ParsedHistory:
    """Parse a watch history without touching the database (format sniffed)."""
    raw = file if isinstance(file, (bytes, str)) else file.read()
    try:
        content = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw.lstrip("﻿")
    except UnicodeDecodeError as error:
        raise TakeoutFormatError("The file isn't UTF-8 text") from error
    stripped = content.lstrip()
    if stripped.startswith(("[", "{")):
        return _parse_json(stripped)
    if stripped.startswith("<"):
        return _parse_html(stripped)
    raise TakeoutFormatError("Not a Takeout watch history: expected JSON or HTML")


def _newest_first(watches: Sequence[_Watch]) -> list[_Watch]:
    """Newest first by watch time; entries without one keep their file order (Takeout
    lists newest first) after those with one."""
    oldest = datetime.min.replace(tzinfo=UTC)
    return sorted(
        watches, key=lambda w: (w.watched_at is not None, w.watched_at or oldest), reverse=True
    )


def _insert_returning(session: Session, sql: str, params: dict[str, Any]) -> bool:
    return session.execute(text(sql), params).first() is not None


def _classify(parsed: _ParsedHistory, entry: _Entry) -> None:
    """Count an entry in its bucket, keeping it if it is an importable watch."""
    try:
        parsed.watches.append(_watch(entry))
    except _Removed:
        parsed.removed += 1
    except _Skipped:
        parsed.skipped += 1
    except _Malformed:
        parsed.malformed += 1


def _watch(entry: _Entry) -> _Watch:
    if entry.is_ad:
        raise _Skipped
    if entry.video_url is None:
        # "Watched a video that has been removed" has no link; other activity may not.
        if entry.title.startswith(_WATCHED_PREFIX):
            raise _Removed
        raise _Skipped
    video_id = _video_id(entry.video_url)
    if entry.channel_url is None:
        # A private or removed video keeps its link but loses its channel and title.
        raise _Removed
    channel_id = _channel_id(entry.channel_url)
    return _Watch(
        video_id=video_id,
        title=entry.title.removeprefix(_WATCHED_PREFIX).strip() or video_id,
        channel_id=channel_id,
        channel_title=(entry.channel_title or "").strip() or channel_id,
        watched_at=entry.watched_at,
    )


def _video_id(url: str) -> str:
    try:
        parsed = parse_youtube_url(url)
    except UnsupportedUrlError:
        if _looks_like_video_link(url):
            raise _Malformed from None
        raise _Skipped from None  # e.g. a search results or post link
    if not isinstance(parsed, ResolvedVideo):
        raise _Skipped
    return parsed.video_id


def _channel_id(url: str) -> str:
    try:
        parsed = parse_youtube_url(url)
    except UnsupportedUrlError:
        raise _Malformed from None
    if not isinstance(parsed, ChannelRef) or parsed.channel_id is None:
        raise _Malformed
    return parsed.channel_id


def _looks_like_video_link(url: str) -> bool:
    return "youtu.be/" in url or "/watch" in url or "/shorts/" in url


# JSON


def _parse_json(content: str) -> _ParsedHistory:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as error:
        raise TakeoutFormatError(f"The file isn't valid JSON: {error}") from error
    if not isinstance(data, list):
        raise TakeoutFormatError("Not a Takeout watch history: expected a JSON list")
    parsed = _ParsedHistory(format="json", watches=[])
    for entry in data:
        try:
            read = _json_entry(entry)
        except _Malformed:
            parsed.malformed += 1
            continue
        _classify(parsed, read)
    return parsed


def _json_entry(entry: object) -> _Entry:
    if not isinstance(entry, dict):
        raise _Malformed
    title = entry.get("title")
    title_url = entry.get("titleUrl")
    time = entry.get("time")
    subtitles = entry.get("subtitles", [])
    details = entry.get("details", [])
    if not isinstance(title, str) or not isinstance(time, str):
        raise _Malformed
    if title_url is not None and not isinstance(title_url, str):
        raise _Malformed
    if not isinstance(subtitles, list) or not isinstance(details, list):
        raise _Malformed
    try:
        watched_at = datetime.fromisoformat(time).astimezone(UTC)
    except ValueError:
        raise _Malformed from None
    channel_url: str | None = None
    channel_title: str | None = None
    if subtitles:
        first: object = subtitles[0]
        if not isinstance(first, dict):
            raise _Malformed
        url = first.get("url")
        name = first.get("name")
        if (url is not None and not isinstance(url, str)) or (
            name is not None and not isinstance(name, str)
        ):
            raise _Malformed
        channel_url, channel_title = url, name
    is_ad = any(
        isinstance(detail, dict) and detail.get("name") == _ADS_DETAIL for detail in details
    )
    return _Entry(
        title=title,
        video_url=title_url,
        channel_url=channel_url,
        channel_title=channel_title,
        watched_at=watched_at,
        is_ad=is_ad,
    )


# HTML

# e.g. "Mar 3, 2024, 9:15:02 PM CET" (Takeout may put a narrow no-break space before PM).
_HTML_TIME = re.compile(
    r"(?P<when>[A-Z][a-z]{2} \d{1,2}, \d{4}, \d{1,2}:\d{2}:\d{2}\s?[AP]M)\s+(?P<zone>\S+)$"
)
_ZONE_OFFSET = re.compile(r"^(?:GMT|UTC)(?P<sign>[+-])(?P<hours>\d{1,2})(?::?(?P<minutes>\d{2}))?$")


class _TakeoutHtmlParser(HTMLParser):
    """Collects each `outer-cell` entry's body: its links and text, and its caption."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.entries: list[dict[str, Any]] = []
        self._divs: list[str] = []  # role of each open div: "outer", "body", "caption", ""
        self._link: dict[str, str] | None = None

    def _role(self) -> str:
        for role in reversed(self._divs):
            if role:
                return role
        return ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "div":
            classes = (dict(attrs).get("class") or "").split()
            role = ""
            if "outer-cell" in classes:
                role = "outer"
                self.entries.append({"links": [], "texts": [], "caption": []})
            elif "content-cell" in classes and self.entries and self._role() == "outer":
                if "mdl-typography--caption" in classes:
                    role = "caption"
                elif "mdl-typography--text-right" not in classes and not self.entries[-1].get(
                    "seen_body"
                ):
                    role = "body"
                    self.entries[-1]["seen_body"] = True
            self._divs.append(role)
        elif tag == "a" and self._role() == "body":
            self._link = {"href": dict(attrs).get("href") or "", "text": ""}

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._divs:
            self._divs.pop()
        elif tag == "a" and self._link is not None:
            self.entries[-1]["links"].append(self._link)
            self._link = None

    def handle_data(self, data: str) -> None:
        role = self._role()
        if role == "body":
            if self._link is not None:
                self._link["text"] += data
            else:
                self.entries[-1]["texts"].append(data)
        elif role == "caption":
            self.entries[-1]["caption"].append(data)


def _parse_html(content: str) -> _ParsedHistory:
    parser = _TakeoutHtmlParser()
    parser.feed(content)
    parser.close()
    if not parser.entries:
        raise TakeoutFormatError("Not a Takeout watch history: no entries found in the HTML")
    parsed = _ParsedHistory(format="html", watches=[])
    for entry in parser.entries:
        try:
            read = _html_entry(entry)
        except _Malformed:
            parsed.malformed += 1
            continue
        _classify(parsed, read)
    return parsed


def _html_entry(entry: dict[str, Any]) -> _Entry:
    if not entry.get("seen_body"):
        raise _Malformed
    links: list[dict[str, str]] = entry["links"]
    texts = [t.strip() for t in entry["texts"] if t.strip()]
    caption = " ".join(" ".join(entry["caption"]).split())
    is_ad = _ADS_DETAIL in caption
    # The body reads "Watched <a video>Title</a><br><a channel>Channel</a><br>Time", or
    # "Watched a video that has been removed<br>Time".
    time_text = texts[-1] if texts else ""
    watched_at = _parse_html_time(time_text)
    if links:
        video, *rest = links
        channel = rest[0] if rest else None
        return _Entry(
            title=f"{_WATCHED_PREFIX}{video['text'].strip()}",
            video_url=video["href"],
            channel_url=channel["href"] if channel else None,
            channel_title=channel["text"] if channel else None,
            watched_at=watched_at,
            is_ad=is_ad,
        )
    if not texts:
        raise _Malformed
    return _Entry(
        title=" ".join(texts[0].split()),
        video_url=None,
        channel_url=None,
        channel_title=None,
        watched_at=watched_at,
        is_ad=is_ad,
    )


def _parse_html_time(value: str) -> datetime | None:
    """A Takeout HTML time, e.g. "Mar 3, 2024, 9:15:02 PM CET", or None if unreadable.

    Only UTC/GMT and numeric offsets are understood; other zone names (CET, PDT, ...)
    are read as UTC, so such times may be off by a few hours.
    """
    match = _HTML_TIME.search(" ".join(value.replace(" ", " ").split()))
    if match is None:
        return None
    when = re.sub(r"\s?([AP]M)$", r" \1", match["when"])
    try:
        naive = datetime.strptime(when, "%b %d, %Y, %I:%M:%S %p")
    except ValueError:
        return None
    zone = _ZONE_OFFSET.match(match["zone"])
    offset = timedelta()
    if zone is not None:
        offset = timedelta(hours=int(zone["hours"]), minutes=int(zone["minutes"] or 0))
        offset = -offset if zone["sign"] == "-" else offset
    return naive.replace(tzinfo=timezone(offset)).astimezone(UTC)
