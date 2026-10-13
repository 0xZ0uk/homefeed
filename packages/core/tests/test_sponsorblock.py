"""SponsorBlock lookups (`HttpSponsorBlock`) and `Playback.sponsor_segments`."""

import hashlib
import io
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit

import pytest

from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway.fake import FakeGateway
from homefeed_core.playback import SEGMENTS_TTL, Playback
from homefeed_core.sponsorblock import (
    HttpSponsorBlock,
    SponsorBlockError,
    SponsorSegment,
    create_sponsorblock,
    segments_from_response,
)
from homefeed_core.user_settings import update_user_settings

VIDEO = "dQw4w9WgXcQ"
PREFIX = hashlib.sha256(VIDEO.encode()).hexdigest()[:4]


def segment(uuid: str, start: Any, end: Any, **fields: Any) -> dict[str, Any]:
    return {
        "UUID": uuid,
        "category": "sponsor",
        "actionType": "skip",
        "segment": [start, end],
        "videoDuration": 212.0,
        "votes": 3,
        **fields,
    }


RESPONSE = [
    {"videoID": "zzzzzzzzzzz", "segments": [segment("other-video", 1, 2)]},
    {
        "videoID": VIDEO,
        "segments": [
            segment("late", 120, 150.5),
            segment("early", 10, 20, category="selfpromo"),
            segment("intro", 0, 5, category="intro"),  # not asked for
            segment("mute", 30, 40, actionType="mute"),
            segment("backwards", 60, 50),
            segment("negative", -1, 3),
            segment("bad-times", "a", 3),
            {"UUID": "no-times", "category": "sponsor"},
            segment("late", 120, 150.5),  # duplicate
            "junk",
        ],
    },
]


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self


class Server:
    """An `open_url` that answers with `body` (or raises `error`) and records requests."""

    def __init__(self, body: Any = RESPONSE, *, error: Exception | None = None) -> None:
        self.body = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.error = error
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, _timeout: float) -> Any:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return FakeResponse(self.body)


def http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://sponsor.invalid", code, "error", cast(Any, {}), None)


def test_skip_segments_asks_by_hash_prefix_and_picks_the_video() -> None:
    server = Server()
    client = HttpSponsorBlock(base_url="https://sponsor.invalid/", open_url=server)

    segments = client.skip_segments(VIDEO)

    assert segments == [
        SponsorSegment("early", "selfpromo", 10.0, 20.0),
        SponsorSegment("late", "sponsor", 120.0, 150.5),
    ]
    [request] = server.requests
    url = urlsplit(request.full_url)
    assert (url.scheme, url.netloc, url.path) == (
        "https",
        "sponsor.invalid",
        f"/api/skipSegments/{PREFIX}",
    )
    assert VIDEO not in request.full_url  # the id itself never leaves
    query = parse_qs(url.query)
    assert json.loads(query["categories"][0]) == ["sponsor", "selfpromo", "interaction"]
    assert json.loads(query["actionTypes"][0]) == ["skip"]


def test_skip_segments_only_in_the_configured_categories() -> None:
    server = Server()
    client = HttpSponsorBlock(categories=["intro", "sponsor"], open_url=server)

    assert [s.id for s in client.skip_segments(VIDEO)] == ["intro", "late"]
    query = parse_qs(urlsplit(server.requests[0].full_url).query)
    assert json.loads(query["categories"][0]) == ["intro", "sponsor"]


def test_no_categories_turns_lookups_off() -> None:
    server = Server()
    assert HttpSponsorBlock(categories=[], open_url=server).skip_segments(VIDEO) == []
    assert server.requests == []


def test_unknown_category_is_rejected() -> None:
    with pytest.raises(ValueError, match="nonsense"):
        HttpSponsorBlock(categories=["sponsor", "nonsense"])


def test_not_found_means_no_segments() -> None:
    client = HttpSponsorBlock(open_url=Server(error=http_error(404)))
    assert client.skip_segments(VIDEO) == []


@pytest.mark.parametrize(
    "server",
    [
        Server(error=http_error(500)),
        Server(error=urllib.error.URLError("connection refused")),
        Server(error=TimeoutError("timed out")),
        Server(b"<html>"),
        Server({"not": "a list"}),
    ],
)
def test_failures_raise_sponsorblock_error(server: Server) -> None:
    with pytest.raises(SponsorBlockError):
        HttpSponsorBlock(open_url=server).skip_segments(VIDEO)


def test_segments_from_response_without_the_video() -> None:
    assert segments_from_response([{"videoID": "zzzzzzzzzzz"}], VIDEO, ["sponsor"]) == []
    assert segments_from_response([], VIDEO, ["sponsor"]) == []


def test_create_sponsorblock_reads_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    monkeypatch.setenv("SPONSORBLOCK_URL", "https://sb.invalid")
    monkeypatch.setenv("SPONSORBLOCK_CATEGORIES", " intro , outro,")
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    server = Server([])
    try:
        client = create_sponsorblock()
        assert isinstance(client, HttpSponsorBlock)
        client._open_url = server  # pyright: ignore[reportPrivateUsage]
        client.skip_segments(VIDEO)
        # The categories are the user setting's, read on each lookup.
        with get_session_factory().begin() as session:
            update_user_settings(session, {"sponsorblock_categories": ["filler"]})
        client.skip_segments(VIDEO)
        with get_session_factory().begin() as session:
            update_user_settings(session, {"sponsorblock_categories": []})
        assert client.skip_segments(VIDEO) == []
    finally:
        get_session_factory().kw["bind"].dispose()
        get_settings.cache_clear()
        get_session_factory.cache_clear()
    urls = [request.full_url for request in server.requests]
    assert len(urls) == 2  # none with skipping off
    assert urls[0].startswith("https://sb.invalid/api/skipSegments/")
    categories = [json.loads(parse_qs(urlsplit(url).query)["categories"][0]) for url in urls]
    assert categories == [["intro", "outro"], ["filler"]]


# Playback.sponsor_segments


class FakeSponsorBlock:
    def __init__(self) -> None:
        self.segments: list[SponsorSegment] = [SponsorSegment("a", "sponsor", 1.0, 2.0)]
        self.error: SponsorBlockError | None = None
        self.calls: list[str] = []

    def skip_segments(self, video_id: str) -> list[SponsorSegment]:
        self.calls.append(video_id)
        if self.error is not None:
            raise self.error
        return list(self.segments)


def test_playback_caches_segments_for_a_while() -> None:
    clock = [datetime(2026, 10, 13, tzinfo=UTC)]
    sponsorblock = FakeSponsorBlock()
    playback = Playback(FakeGateway(), sponsorblock=sponsorblock, now=lambda: clock[0])

    first = playback.sponsor_segments(VIDEO)
    first.clear()  # callers can't change the cache
    assert playback.sponsor_segments(VIDEO) == [SponsorSegment("a", "sponsor", 1.0, 2.0)]
    assert sponsorblock.calls == [VIDEO]

    sponsorblock.segments = []
    clock[0] += SEGMENTS_TTL + timedelta(seconds=1)
    assert playback.sponsor_segments(VIDEO) == []
    assert sponsorblock.calls == [VIDEO, VIDEO]


def test_playback_does_not_cache_failures() -> None:
    sponsorblock = FakeSponsorBlock()
    sponsorblock.error = SponsorBlockError("down")
    playback = Playback(FakeGateway(), sponsorblock=sponsorblock)

    with pytest.raises(SponsorBlockError):
        playback.sponsor_segments(VIDEO)
    sponsorblock.error = None
    assert len(playback.sponsor_segments(VIDEO)) == 1
    assert sponsorblock.calls == [VIDEO, VIDEO]


def test_playback_forgets_segments_when_asked() -> None:
    sponsorblock = FakeSponsorBlock()
    playback = Playback(FakeGateway(), sponsorblock=sponsorblock)
    playback.sponsor_segments(VIDEO)

    playback.forget_sponsor_segments()  # the categories changed

    playback.sponsor_segments(VIDEO)
    assert sponsorblock.calls == [VIDEO, VIDEO]
