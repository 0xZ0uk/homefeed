"""External sources: subreddits, RSS/Atom feeds and link pages whose YouTube links
become candidates.

Sources are added by hand (kind, URL and schedule) and stored in `external_sources`.
`ExternalSourcesSource` is the `CandidateSource` (named `external`) that fetches the due
ones, extracts their links (see homefeed_core.link_extraction) and turns the links to
YouTube videos into candidates. Every link goes through `Gateway.resolve_url`, which
also tells which ones are YouTube at all; links to channels, playlists and Shorts are
ignored. A video's `source_detail` is its source's label (e.g. "r/videos").

Only non-YouTube pages are fetched here (with `PageFetcher`); YouTube URLs are refused
as sources and as redirect targets, since only the Gateway talks to YouTube.

Each source is fetched again one `schedule` interval after a success. After `n`
consecutive failures it is retried `RETRY_AFTER * 2 ** (n - 1)` later, never later than
its schedule's interval. A source that fails is recorded and skipped; the candidate
source as a whole fails only when every due source did.
"""

import logging
import re
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.client import HTTPResponse
from typing import Any, Literal, Protocol, get_args
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.candidates import FoundVideo
from homefeed_core.gateway import (
    Gateway,
    GatewayError,
    ResolvedVideo,
    UnsupportedUrlError,
)
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.gateway.urls import is_youtube_url
from homefeed_core.link_extraction import (
    ExtractedLinks,
    ExtractionFailedError,
    links_from_feed,
    links_from_html,
    links_from_subreddit_json,
)

logger = logging.getLogger(__name__)

# Stored as `candidates.source`.
EXTERNAL = "external"

Kind = Literal["subreddit", "rss", "page"]
Schedule = Literal["hourly", "daily", "weekly"]

KINDS: tuple[Kind, ...] = get_args(Kind)
SCHEDULES: tuple[Schedule, ...] = get_args(Schedule)
DEFAULT_SCHEDULE: Schedule = "daily"
SCHEDULE_INTERVALS: Mapping[Schedule, timedelta] = {
    "hourly": timedelta(hours=1),
    "daily": timedelta(days=1),
    "weekly": timedelta(weeks=1),
}
# First retry after a failed fetch; doubles with each further failure.
RETRY_AFTER = timedelta(minutes=15)

URL_MAX_LENGTH = 2000
# Posts read from a subreddit per fetch (Reddit's maximum).
SUBREDDIT_POSTS = 100

DEFAULT_BATCH_SIZE = 50  # due sources fetched per run
DEFAULT_MAX_VIDEOS_PER_SOURCE = 30  # videos taken from one source per fetch
DEFAULT_MAX_YOUTUBE_LINKS_PER_SOURCE = 100  # YouTube links resolved per source per fetch

_SUBREDDIT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_]{1,20}$")
_REDDIT_HOSTS = {"reddit.com", "old.reddit.com", "new.reddit.com", "np.reddit.com", "m.reddit.com"}


class InvalidSourceError(ValueError):
    """The URL can't be a source of this kind (malformed, not http(s), a YouTube link)."""


@dataclass(frozen=True)
class ExternalSource:
    id: int
    kind: Kind
    url: str  # canonical, e.g. https://www.reddit.com/r/videos
    label: str  # what to call it: "r/videos", the feed's or page's title, or its URL
    title: str | None  # the source's own title, from its last successful fetch
    schedule: Schedule
    next_fetch_at: str  # ISO 8601 UTC
    last_fetched_at: str | None
    last_success_at: str | None
    consecutive_failures: int
    last_error: str | None
    last_found_count: int | None  # YouTube videos found by the last successful fetch
    created_at: str
    updated_at: str


# Normalization


def normalize_source_url(kind: Kind, url: str) -> str:
    """The canonical URL of a source. Raises `InvalidSourceError` if it can't be one.

    Subreddits accept "r/name", "name" or any Reddit link into the subreddit and become
    `https://www.reddit.com/r/name`; feeds and pages need an absolute http(s) URL (the
    scheme defaults to https) that isn't a YouTube link.
    """
    if kind not in KINDS:
        raise InvalidSourceError(f"Unknown source kind {kind!r}")
    raw = url.strip()
    if not raw:
        raise InvalidSourceError("URL is empty")
    if len(raw) > URL_MAX_LENGTH:
        raise InvalidSourceError(f"URL is longer than {URL_MAX_LENGTH} characters")
    if kind == "subreddit":
        return f"https://www.reddit.com/r/{_subreddit_name(raw)}"
    if is_youtube_url(raw):
        raise InvalidSourceError(
            "YouTube links can't be external sources; subscribe to the channel instead"
        )
    if "://" not in raw:
        raw = f"https://{raw}"
    try:
        parts = urlsplit(raw)
        hostname = parts.hostname
    except ValueError as error:
        raise InvalidSourceError(f"Not a valid URL: {url.strip()!r}") from error
    if parts.scheme.lower() not in ("http", "https") or not hostname or "." not in hostname:
        raise InvalidSourceError(f"Not a web address: {url.strip()!r}")
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, "")
    )


def _subreddit_name(raw: str) -> str:
    text_ = raw
    if "://" in text_ or text_.lower().split("/", 1)[0].removeprefix("www.") in _REDDIT_HOSTS:
        if "://" not in text_:
            text_ = f"https://{text_}"
        try:
            parts = urlsplit(text_)
            host = (parts.hostname or "").lower().removeprefix("www.")
        except ValueError as error:
            raise InvalidSourceError(f"Not a subreddit: {raw!r}") from error
        if host not in _REDDIT_HOSTS:
            raise InvalidSourceError(f"Not a Reddit link: {raw!r}")
        text_ = parts.path
    segments = [s for s in text_.split("/") if s]
    if len(segments) >= 2 and segments[0].lower() == "r":
        name = segments[1]
    elif len(segments) == 1:
        name = segments[0]
    else:
        raise InvalidSourceError(f"Not a subreddit: {raw!r}")
    if not _SUBREDDIT_NAME.match(name):
        raise InvalidSourceError(f"Not a subreddit name: {name!r}")
    return name


def _check_schedule(schedule: str) -> Schedule:
    if schedule not in SCHEDULES:
        raise InvalidSourceError(f"Unknown schedule {schedule!r}")
    return schedule  # pyright: ignore[reportReturnType]


# CRUD

_COLUMNS = (
    "id, kind, url, title, schedule, next_fetch_at, last_fetched_at, last_success_at, "
    "consecutive_failures, last_error, last_found_count, created_at, updated_at"
)


def list_sources(session: Session) -> list[ExternalSource]:
    """All external sources, by kind and then URL."""
    rows = session.execute(text(f"SELECT {_COLUMNS} FROM external_sources ORDER BY kind, url, id"))
    return [_from_row(row) for row in rows]


def get_source(session: Session, source_id: int) -> ExternalSource | None:
    row = session.execute(
        text(f"SELECT {_COLUMNS} FROM external_sources WHERE id = :id"),
        {"id": source_id},
    ).one_or_none()
    return None if row is None else _from_row(row)


def add_source(
    session: Session,
    kind: Kind,
    url: str,
    schedule: Schedule = DEFAULT_SCHEDULE,
    *,
    now: datetime | None = None,
) -> tuple[ExternalSource, bool]:
    """Add a source (its URL normalized with `normalize_source_url`), due right away.

    Returns the source and whether it is new; adding a URL again (in any case) returns
    the existing source unchanged. Raises `InvalidSourceError` for a bad URL or schedule.
    """
    url = normalize_source_url(kind, url)
    schedule = _check_schedule(schedule)
    row = session.execute(
        text(
            """
            INSERT INTO external_sources (kind, url, schedule, next_fetch_at, created_at,
                                          updated_at)
            VALUES (:kind, :url, :schedule, coalesce(:now, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    coalesce(:now, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    coalesce(:now, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')))
            ON CONFLICT (url) DO NOTHING
            RETURNING """
            + _COLUMNS
        ),
        {
            "kind": kind,
            "url": url,
            "schedule": schedule,
            "now": format_timestamp(now) if now else None,
        },
    ).one_or_none()
    if row is not None:
        return _from_row(row), True
    existing = session.execute(
        text(f"SELECT {_COLUMNS} FROM external_sources WHERE url = :url"),
        {"url": url},
    ).one()
    return _from_row(existing), False


def update_source(
    session: Session,
    source_id: int,
    *,
    schedule: Schedule | None = None,
    now: datetime | None = None,
) -> ExternalSource | None:
    """Change a source's schedule; its next fetch moves to one new interval after the
    last success (or stays due if it was never fetched successfully). Returns `None` if
    there is no such source."""
    source = get_source(session, source_id)
    if source is None or schedule is None:
        return source
    schedule = _check_schedule(schedule)
    next_fetch_at = source.next_fetch_at
    if source.last_success_at is not None and source.consecutive_failures == 0:
        last_success = datetime.fromisoformat(source.last_success_at)
        next_fetch_at = format_timestamp(last_success + SCHEDULE_INTERVALS[schedule])
    row = session.execute(
        text(
            """
            UPDATE external_sources
            SET schedule = :schedule, next_fetch_at = :next_fetch_at,
                updated_at = coalesce(:now, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            WHERE id = :id
            RETURNING """
            + _COLUMNS
        ),
        {
            "id": source_id,
            "schedule": schedule,
            "next_fetch_at": next_fetch_at,
            "now": format_timestamp(now) if now else None,
        },
    ).one()
    return _from_row(row)


def delete_source(session: Session, source_id: int) -> bool:
    """Remove a source (candidates it found stay). Returns whether it existed."""
    deleted = session.execute(
        text("DELETE FROM external_sources WHERE id = :id RETURNING id"), {"id": source_id}
    ).first()
    return deleted is not None


def due_sources(
    session: Session, now: datetime, *, limit: int | None = None
) -> list[ExternalSource]:
    """Sources whose next fetch time has come, most overdue first."""
    rows = session.execute(
        text(
            f"""
            SELECT {_COLUMNS} FROM external_sources
            WHERE next_fetch_at <= :now
            ORDER BY next_fetch_at, id
            LIMIT :limit
            """
        ),
        {"now": format_timestamp(now), "limit": -1 if limit is None else limit},
    )
    return [_from_row(row) for row in rows]


def next_fetch_after_failure(source: ExternalSource, now: datetime) -> datetime:
    """When to retry a source that just failed (its `consecutive_failures + 1`th time)."""
    failures = source.consecutive_failures + 1
    interval = SCHEDULE_INTERVALS[source.schedule]
    return now + min(RETRY_AFTER * 2 ** min(failures - 1, 20), interval)


def _record_success(
    session: Session, source: ExternalSource, now: datetime, title: str | None, found: int
) -> None:
    session.execute(
        text(
            """
            UPDATE external_sources
            SET next_fetch_at = :next_fetch_at, last_fetched_at = :now, last_success_at = :now,
                consecutive_failures = 0, last_error = NULL, last_found_count = :found,
                title = coalesce(:title, title)
            WHERE id = :id
            """
        ),
        {
            "id": source.id,
            "next_fetch_at": format_timestamp(now + SCHEDULE_INTERVALS[source.schedule]),
            "now": format_timestamp(now),
            "title": title[:200] if title else None,
            "found": found,
        },
    )


def _record_failure(session: Session, source: ExternalSource, now: datetime, error: str) -> None:
    session.execute(
        text(
            """
            UPDATE external_sources
            SET next_fetch_at = :next_fetch_at, last_fetched_at = :now,
                consecutive_failures = consecutive_failures + 1, last_error = :error
            WHERE id = :id
            """
        ),
        {
            "id": source.id,
            "next_fetch_at": format_timestamp(next_fetch_after_failure(source, now)),
            "now": format_timestamp(now),
            "error": error[:500],
        },
    )


def _label(kind: Kind, url: str, title: str | None) -> str:
    if kind == "subreddit":
        return "r/" + url.rstrip("/").rsplit("/", 1)[-1]
    if title:
        return title
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    return f"{(parts.hostname or '').removeprefix('www.')}{path}"


def _from_row(row: Any) -> ExternalSource:
    (id_, kind, url, title, schedule, *rest) = row
    return ExternalSource(id_, kind, url, _label(kind, url, title), title, schedule, *rest)


# Fetching


class ExternalFetchError(Exception):
    """A source's URL couldn't be fetched."""


class PageFetcher(Protocol):
    def __call__(self, url: str) -> bytes:
        """The body at `url`. Raises `ExternalFetchError` if it can't be fetched."""
        ...


def fetch_url(source: ExternalSource) -> str:
    """What to download for a source: a subreddit's hot listing as JSON, else its URL."""
    if source.kind == "subreddit":
        return f"{source.url}/hot.json?limit={SUBREDDIT_POSTS}&raw_json=1"
    return source.url


def extract_links(source: ExternalSource, body: bytes) -> ExtractedLinks:
    """The links in what `source` served. Raises `ExtractionFailedError` if it isn't a
    subreddit listing or a feed (pages always parse)."""
    if source.kind == "subreddit":
        return links_from_subreddit_json(body)
    if source.kind == "rss":
        return links_from_feed(body, source.url)
    return links_from_html(body, source.url)


TIMEOUT_SECONDS = 20
MAX_PAGE_BYTES = 5_000_000
_USER_AGENT = "homefeed/0.1 (personal feed reader)"

OpenUrl = Callable[[urllib.request.Request, float], HTTPResponse]


class _RefuseYouTubeRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> urllib.request.Request | None:
        if is_youtube_url(newurl):
            raise ExternalFetchError(f"{req.full_url} redirects to YouTube ({newurl})")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_RefuseYouTubeRedirects)


def _urlopen(request: urllib.request.Request, timeout: float) -> HTTPResponse:
    return _opener.open(request, timeout=timeout)


class HttpPageFetcher:
    """`PageFetcher` over HTTP(S). Refuses YouTube URLs, including as redirect targets."""

    def __init__(self, *, open_url: OpenUrl = _urlopen, timeout: float = TIMEOUT_SECONDS) -> None:
        self._open_url = open_url
        self._timeout = timeout

    def __call__(self, url: str) -> bytes:
        if is_youtube_url(url):
            raise ExternalFetchError(f"Refusing to fetch a YouTube URL outside the Gateway: {url}")
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/json, application/rss+xml, application/atom+xml, "
                "application/xml, text/xml, text/html;q=0.9, */*;q=0.5",
            },
        )
        try:
            with self._open_url(request, self._timeout) as response:
                body = response.read(MAX_PAGE_BYTES + 1)
        except urllib.error.HTTPError as error:
            raise ExternalFetchError(f"HTTP Error {error.code} fetching {url}") from error
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise ExternalFetchError(f"Could not fetch {url}: {error}") from error
        if len(body) > MAX_PAGE_BYTES:
            raise ExternalFetchError(f"{url} is larger than {MAX_PAGE_BYTES} bytes")
        return body


# The candidate source

# The worker's external-sources job and the daily feed job both run this source; one
# waits for the other, then finds the sources it fetched no longer due.
_fetch_lock = threading.Lock()


class ExternalSourcesSource:
    """YouTube videos linked from the due external sources (see the module docstring).

    Each fetched source contributes up to `max_videos_per_source` videos, in the order
    they're linked, attributed to it (`source_detail` = its label). Rated videos and
    Shorts are left out. Videos not stored yet are looked up with `Gateway.get_video`.
    """

    name = EXTERNAL

    def __init__(
        self,
        sessions: sessionmaker[Session],
        gateway: Gateway,
        fetch: PageFetcher | None = None,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_videos_per_source: int = DEFAULT_MAX_VIDEOS_PER_SOURCE,
        max_youtube_links_per_source: int = DEFAULT_MAX_YOUTUBE_LINKS_PER_SOURCE,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = sessions
        self._gateway = gateway
        self._fetch = fetch or HttpPageFetcher()
        self._batch_size = batch_size
        self._max_videos = max_videos_per_source
        self._max_links = max_youtube_links_per_source
        self._now = now

    def fetch(self) -> list[FoundVideo]:
        with _fetch_lock:
            return self._fetch_due()

    def _fetch_due(self) -> list[FoundVideo]:
        with self._sessions() as session:
            due = due_sources(session, self._now(), limit=self._batch_size)
            rated = set(session.execute(text("SELECT video_id FROM ratings")).scalars())
        found: list[FoundVideo] = []
        errors: list[Exception] = []
        for source in due:
            started = time.monotonic()
            try:
                extracted = extract_links(source, self._fetch(fetch_url(source)))
            except (ExternalFetchError, ExtractionFailedError) as error:
                logger.warning("External source %s (%s) failed: %s", source.id, source.url, error)
                errors.append(error)
                with self._sessions.begin() as session:
                    _record_failure(session, source, self._now(), str(error))
                continue
            label = _label(source.kind, source.url, extracted.title or source.title)
            videos = self._videos(extracted.links, label, skip=rated)
            with self._sessions.begin() as session:
                _record_success(session, source, self._now(), extracted.title, len(videos))
            logger.info(
                "External source %s (%s): %d links, %d videos in %.1fs",
                source.id,
                source.url,
                len(extracted.links),
                len(videos),
                time.monotonic() - started,
            )
            found += videos
        if errors and len(errors) == len(due):
            raise errors[-1]
        return found

    def _videos(self, links: list[str], label: str, *, skip: set[str]) -> list[FoundVideo]:
        video_ids: list[str] = []
        youtube_links = 0
        for link in links:
            if youtube_links >= self._max_links or len(video_ids) >= self._max_videos:
                break
            try:
                resolved = self._gateway.resolve_url(link)
            except UnsupportedUrlError:
                continue  # not YouTube, or nothing we can use
            except (GatewayError, ValueError) as error:
                youtube_links += 1
                logger.info("Could not resolve %s: %s", link, error)
                continue
            youtube_links += 1
            if not isinstance(resolved, ResolvedVideo) or resolved.is_short_url:
                continue
            if resolved.video_id in skip or resolved.video_id in video_ids:
                continue
            video_ids.append(resolved.video_id)
        found: list[FoundVideo] = []
        for video_id in video_ids:
            video = self._video(video_id, label)
            if video is not None:
                found.append(video)
        return found

    def _video(self, video_id: str, label: str) -> FoundVideo | None:
        with self._sessions() as session:
            stored = session.execute(
                text(
                    """
                    SELECT v.title, v.channel_id, c.title FROM videos AS v
                    JOIN channels AS c ON c.id = v.channel_id
                    WHERE v.id = :id
                    """
                ),
                {"id": video_id},
            ).one_or_none()
        if stored is not None:
            title, channel_id, channel_title = stored
            return FoundVideo(video_id, title, channel_id, channel_title, source_detail=label)
        try:
            video = self._gateway.get_video(video_id)
        except GatewayError as error:
            logger.info("Skipping linked video %s: %s", video_id, error)
            return None
        if video.is_short:
            return None
        return FoundVideo(
            video_id=video.id,
            title=video.title,
            channel_id=video.channel_id,
            channel_title=video.channel_title,
            source_detail=label,
            channel_handle=video.channel_handle,
            duration_seconds=video.duration_seconds,
            view_count=video.view_count,
            thumbnail_url=video.thumbnail_url,
            live_status=video.live_status,
        )
