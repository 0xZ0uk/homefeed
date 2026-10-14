import io
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from http.client import HTTPResponse
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.candidates import generate, list_candidates
from homefeed_core.composer import explain
from homefeed_core.db import open_database
from homefeed_core.external_sources import (
    EXTERNAL,
    ExternalFetchError,
    ExternalSource,
    ExternalSourcesSource,
    HttpPageFetcher,
    InvalidSourceError,
    add_source,
    delete_source,
    due_sources,
    get_source,
    list_sources,
    normalize_source_url,
    update_source,
)
from homefeed_core.gateway import ExtractionError
from homefeed_core.gateway.fake import FakeGateway, make_channel, make_video
from homefeed_core.ranker import RankCandidate, ScoreBreakdown, ScoredCandidate
from homefeed_core.ratings import set_rating

FIXTURES = Path(__file__).parent / "fixtures" / "external"
T0 = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
SUBREDDIT = "https://www.reddit.com/r/Documentaries"
SUBREDDIT_JSON = f"{SUBREDDIT}/hot.json?limit=100&raw_json=1"
FEED = "https://slowscience.example.org/feed"
PAGE = "https://lectures.example.com/best"


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class FakeFetcher:
    def __init__(self, pages: dict[str, bytes | Exception]) -> None:
        self.pages = pages
        self.requested: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.requested.append(url)
        page = self.pages.get(url, ExternalFetchError(f"HTTP Error 404 fetching {url}"))
        if isinstance(page, Exception):
            raise page
        return page


def gateway_with(*video_ids: str, **fields: object) -> FakeGateway:
    gateway = FakeGateway()
    channel = make_channel("UC" + "d" * 22, title="Deep Dives")
    for video_id in video_ids:
        gateway.add_video(make_video(video_id, channel=channel, **fields))
    return gateway


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at


def add(sessions: sessionmaker[Session], kind: str, url: str, schedule: str = "daily") -> int:
    with sessions.begin() as session:
        source, created = add_source(session, kind, url, schedule, now=T0)  # type: ignore[arg-type]
    assert created
    return source.id


def get(sessions: sessionmaker[Session], source_id: int) -> ExternalSource:
    with sessions() as session:
        source = get_source(session, source_id)
    assert source is not None
    return source


# Normalization and CRUD


@pytest.mark.parametrize(
    "raw",
    [
        "videos",
        "r/videos",
        "/r/videos/",
        "https://www.reddit.com/r/videos/",
        "reddit.com/r/videos/top/?t=week",
        "https://old.reddit.com/r/videos/comments/abc/some_post/",
    ],
)
def test_subreddits_normalize_to_their_listing_page(raw: str) -> None:
    assert normalize_source_url("subreddit", raw) == "https://www.reddit.com/r/videos"


@pytest.mark.parametrize(
    "raw", ["", "r/", "r/x", "https://example.com/r/videos", "u/someone/posts", "r/no spaces"]
)
def test_bad_subreddits_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidSourceError):
        normalize_source_url("subreddit", raw)


def test_feed_and_page_urls_are_normalized() -> None:
    assert (
        normalize_source_url("rss", " Example.COM/feed.xml#top ") == "https://example.com/feed.xml"
    )
    assert normalize_source_url("page", "http://example.com") == "http://example.com/"


@pytest.mark.parametrize(
    "raw",
    [
        "ftp://example.com/feed",
        "localhost",
        "https://www.youtube.com/feeds/videos.xml?channel_id=UC4QobU6STFB0P71PMvOGN5A",
        "youtu.be/aaaaaaaaaaa",
        "http://[::1",
        "x" * 2001,
    ],
)
def test_bad_feed_urls_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidSourceError):
        normalize_source_url("rss", raw)


def test_add_list_update_delete(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        reddit, created = add_source(session, "subreddit", "r/Documentaries", "hourly")
        again, created_again = add_source(session, "subreddit", "R/documentaries")
        feed, _ = add_source(session, "rss", FEED)

    assert created and not created_again
    assert again == reddit
    assert (reddit.kind, reddit.url, reddit.label, reddit.schedule) == (
        "subreddit",
        SUBREDDIT,
        "r/Documentaries",
        "hourly",
    )
    assert (feed.label, feed.schedule, feed.title) == (
        "slowscience.example.org/feed",
        "daily",
        None,
    )
    assert reddit.last_fetched_at is None and reddit.consecutive_failures == 0

    with sessions.begin() as session:
        assert [s.id for s in list_sources(session)] == [feed.id, reddit.id]  # rss < subreddit
        updated = update_source(session, feed.id, schedule="weekly")
        assert updated is not None and updated.schedule == "weekly"
        assert updated.next_fetch_at == feed.next_fetch_at  # never fetched: still due
        assert update_source(session, 999, schedule="hourly") is None
        with pytest.raises(InvalidSourceError):
            update_source(session, feed.id, schedule="monthly")  # type: ignore[arg-type]
        assert delete_source(session, feed.id)
        assert not delete_source(session, feed.id)
        assert [s.id for s in list_sources(session)] == [reddit.id]


def test_add_rejects_unknown_schedule(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(InvalidSourceError), sessions.begin() as session:
        add_source(session, "rss", FEED, "monthly")  # type: ignore[arg-type]


# Fetching as a candidate source


def test_subreddit_videos_become_candidates(sessions: sessionmaker[Session]) -> None:
    source_id = add(sessions, "subreddit", "r/Documentaries")
    gateway = gateway_with("aaaaaaaaaaa", "bbbbbbbbbbb", "sssssssssss")
    fetch = FakeFetcher({SUBREDDIT_JSON: fixture("subreddit_hot.json")})
    source = ExternalSourcesSource(sessions, gateway, fetch, now=Clock(T0))

    report = generate([source], sessions=sessions, now=T0)

    assert fetch.requested == [SUBREDDIT_JSON]
    # Shorts links, channel links and other sites are left out.
    assert report.new == {EXTERNAL: ["aaaaaaaaaaa", "bbbbbbbbbbb"]}
    with sessions() as session:
        pool = list_candidates(session)
    assert {(c.video_id, c.source, c.source_detail) for c in pool} == {
        ("aaaaaaaaaaa", EXTERNAL, "r/Documentaries"),
        ("bbbbbbbbbbb", EXTERNAL, "r/Documentaries"),
    }
    # Every link went through the Gateway; only new videos were looked up.
    resolved = [target for op, target in gateway.calls if op == "resolve_url"]
    assert "https://vimeo.com/123456789" in resolved
    assert "https://www.youtube.com/@deepdives" in resolved
    assert [t for op, t in gateway.calls if op == "get_video"] == ["aaaaaaaaaaa", "bbbbbbbbbbb"]

    stored = get(sessions, source_id)
    assert stored.title == "r/Documentaries"
    assert stored.last_success_at == stored.last_fetched_at == "2026-10-12T06:00:00.000Z"
    assert stored.next_fetch_at == "2026-10-13T06:00:00.000Z"
    assert stored.last_found_count == 2


def test_feeds_and_pages_use_their_title_as_label(sessions: sessionmaker[Session]) -> None:
    add(sessions, "rss", FEED)
    add(sessions, "page", PAGE)
    gateway = gateway_with(*"ccccccccccc ddddddddddd eeeeeeeeeee ggggggggggg hhhhhhhhhhh".split())
    fetch = FakeFetcher({FEED: fixture("feed_rss.xml"), PAGE: fixture("link_page.html")})

    found = ExternalSourcesSource(sessions, gateway, fetch, now=Clock(T0)).fetch()

    assert [(v.video_id, v.source_detail) for v in found] == [
        ("ccccccccccc", "Slow Science Weekly"),
        ("ddddddddddd", "Slow Science Weekly"),
        ("eeeeeeeeeee", "Slow Science Weekly"),
        ("ggggggggggg", "Best lectures of 2026"),
        ("hhhhhhhhhhh", "Best lectures of 2026"),
        # iiiiiiiiiii is linked too but unavailable, so it's skipped.
    ]
    with sessions() as session:
        assert [s.label for s in list_sources(session)] == [
            "Best lectures of 2026",
            "Slow Science Weekly",
        ]


def test_rated_and_stored_videos(sessions: sessionmaker[Session]) -> None:
    add(sessions, "page", PAGE)
    gateway = gateway_with("ggggggggggg", "hhhhhhhhhhh", "iiiiiiiiiii")
    with sessions.begin() as session:
        session.execute(text("INSERT INTO channels (id, title) VALUES ('UCstored', 'Stored')"))
        session.execute(
            text(
                "INSERT INTO videos (id, channel_id, title) "
                "VALUES ('ggggggggggg', 'UCstored', 'Kept'), ('hhhhhhhhhhh', 'UCstored', 'R')"
            )
        )
        set_rating(session, "hhhhhhhhhhh", 8)
    fetch = FakeFetcher({PAGE: fixture("link_page.html")})

    found = ExternalSourcesSource(sessions, gateway, fetch, now=Clock(T0)).fetch()

    assert [(v.video_id, v.title, v.channel_title) for v in found] == [
        ("ggggggggggg", "Kept", "Stored"),  # already stored: not looked up again
        ("iiiiiiiiiii", "Video iiiiiiiiiii", "Deep Dives"),
    ]
    assert [t for op, t in gateway.calls if op == "get_video"] == ["iiiiiiiiiii"]


def test_per_source_video_cap(sessions: sessionmaker[Session]) -> None:
    add(sessions, "page", PAGE)
    gateway = gateway_with("ggggggggggg", "hhhhhhhhhhh", "iiiiiiiiiii")
    fetch = FakeFetcher({PAGE: fixture("link_page.html")})

    source = ExternalSourcesSource(sessions, gateway, fetch, max_videos_per_source=2)

    assert [v.video_id for v in source.fetch()] == ["ggggggggggg", "hhhhhhhhhhh"]


def test_only_due_sources_are_fetched(sessions: sessionmaker[Session]) -> None:
    hourly = add(sessions, "rss", FEED, "hourly")
    add(sessions, "page", PAGE, "weekly")
    fetch = FakeFetcher({FEED: fixture("feed_rss.xml"), PAGE: fixture("link_page.html")})
    clock = Clock(T0)
    source = ExternalSourcesSource(sessions, FakeGateway(), fetch, now=clock)

    source.fetch()
    clock.at = T0 + timedelta(minutes=59)
    source.fetch()
    clock.at = T0 + timedelta(hours=1)
    source.fetch()

    assert fetch.requested == [FEED, PAGE, FEED]
    with sessions() as session:
        assert [s.id for s in due_sources(session, T0 + timedelta(days=6))] == [hourly]


def test_changing_the_schedule_moves_the_next_fetch(sessions: sessionmaker[Session]) -> None:
    source_id = add(sessions, "rss", FEED, "weekly")
    fetch = FakeFetcher({FEED: fixture("feed_rss.xml")})
    ExternalSourcesSource(sessions, FakeGateway(), fetch, now=Clock(T0)).fetch()
    assert get(sessions, source_id).next_fetch_at == "2026-10-19T06:00:00.000Z"

    with sessions.begin() as session:
        update_source(session, source_id, schedule="hourly")

    assert get(sessions, source_id).next_fetch_at == "2026-10-12T07:00:00.000Z"


def test_a_failing_source_backs_off_and_others_still_run(
    sessions: sessionmaker[Session],
) -> None:
    broken = add(sessions, "rss", "https://broken.example.com/feed", "daily")
    not_a_feed = add(sessions, "rss", "https://html.example.com/", "daily")
    add(sessions, "page", PAGE)
    gateway = gateway_with("ggggggggggg")
    fetch = FakeFetcher(
        {PAGE: fixture("link_page.html"), "https://html.example.com/": b"<html></html>"}
    )
    clock = Clock(T0)
    source = ExternalSourcesSource(sessions, gateway, fetch, now=clock)

    assert [v.video_id for v in source.fetch()] == ["ggggggggggg"]

    failed = get(sessions, broken)
    assert failed.consecutive_failures == 1
    assert failed.last_error == "HTTP Error 404 fetching https://broken.example.com/feed"
    assert failed.last_success_at is None
    assert failed.next_fetch_at == "2026-10-12T06:15:00.000Z"
    assert get(sessions, not_a_feed).last_error is not None
    with sessions.begin() as session:
        delete_source(session, not_a_feed)

    clock.at = T0 + timedelta(minutes=15)
    with pytest.raises(ExternalFetchError):  # the only due source failed
        source.fetch()
    assert get(sessions, broken).next_fetch_at == "2026-10-12T06:45:00.000Z"  # 30 min later

    # Backoff never exceeds the schedule's interval.
    for _ in range(10):
        clock.at = datetime.fromisoformat(get(sessions, broken).next_fetch_at)
        source_ = ExternalSourcesSource(sessions, gateway, FakeFetcher({}), now=clock)
        with pytest.raises(ExternalFetchError):
            source_.fetch()
    final = get(sessions, broken)
    assert datetime.fromisoformat(final.next_fetch_at) - clock.at == timedelta(days=1)

    # A success resets it.
    fetch.pages["https://broken.example.com/feed"] = fixture("feed_rss.xml")
    clock.at = datetime.fromisoformat(final.next_fetch_at)
    source.fetch()
    recovered = get(sessions, broken)
    assert (recovered.consecutive_failures, recovered.last_error) == (0, None)


def test_the_source_fails_only_when_every_due_source_did(
    sessions: sessionmaker[Session],
) -> None:
    add(sessions, "rss", FEED)
    source = ExternalSourcesSource(sessions, FakeGateway(), FakeFetcher({}), now=Clock(T0))

    report = generate([source], sessions=sessions, now=T0)

    assert report.failed == {EXTERNAL: f"HTTP Error 404 fetching {FEED}"}


def test_nothing_due_finds_nothing(sessions: sessionmaker[Session]) -> None:
    fetch = FakeFetcher({})
    assert ExternalSourcesSource(sessions, FakeGateway(), fetch).fetch() == []
    assert fetch.requested == []


def test_gateway_failures_skip_the_link(sessions: sessionmaker[Session]) -> None:
    add(sessions, "page", PAGE)
    gateway = gateway_with("ggggggggggg", "hhhhhhhhhhh")
    gateway.fail(
        "resolve_url", "https://www.youtube.com/watch?v=ggggggggggg", ExtractionError("boom")
    )
    fetch = FakeFetcher({PAGE: fixture("link_page.html")})

    found = ExternalSourcesSource(sessions, gateway, fetch, now=Clock(T0)).fetch()

    # g is still found through its embed link.
    assert [v.video_id for v in found] == ["hhhhhhhhhhh", "ggggggggggg"]


def test_explanation_names_the_source() -> None:
    item = ScoredCandidate(
        candidate=RankCandidate(
            "aaaaaaaaaaa", "UC" + "d" * 22, source=EXTERNAL, source_detail="r/videos"
        ),
        breakdown=ScoreBreakdown(),
        channel_prior="neutral",
        channel_rating_count=0,
    )
    assert explain(item) == "Linked from r/videos"


# HTTP


class Response(io.BytesIO):
    pass


def http_fetcher(respond: bytes | Exception) -> tuple[HttpPageFetcher, list[str]]:
    requested: list[str] = []

    def open_url(request: urllib.request.Request, timeout: float) -> HTTPResponse:
        requested.append(request.full_url)
        assert request.get_header("User-agent", "").startswith("homefeed/")
        if isinstance(respond, Exception):
            raise respond
        return cast(HTTPResponse, Response(respond))

    return HttpPageFetcher(open_url=open_url), requested


def test_http_fetcher_returns_the_body() -> None:
    fetch, requested = http_fetcher(b"<rss/>")

    assert fetch(FEED) == b"<rss/>"
    assert requested == [FEED]


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.HTTPError(FEED, 403, "Forbidden", {}, None),  # pyright: ignore[reportArgumentType]
        urllib.error.URLError("timed out"),
        TimeoutError("timed out"),
    ],
)
def test_http_fetcher_errors(error: Exception) -> None:
    fetch, _ = http_fetcher(error)

    with pytest.raises(ExternalFetchError):
        fetch(FEED)


def test_http_fetcher_refuses_youtube() -> None:
    fetch, requested = http_fetcher(b"")

    with pytest.raises(ExternalFetchError):
        fetch("https://www.youtube.com/feeds/videos.xml?channel_id=UC4QobU6STFB0P71PMvOGN5A")
    assert requested == []
