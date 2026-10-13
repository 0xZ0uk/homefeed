"""The yt-dlp Gateway against recorded responses: normalization, retries, recording."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from gateway_fixtures import LIVE_TESTS, Replay
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.db import open_database
from homefeed_core.gateway import (
    CaptionSegment,
    Chapter,
    ExtractionError,
    Gateway,
    MemoryEventRecorder,
    RateLimitedError,
    RateLimiter,
    ResolvedChannel,
    ResolvedPlaylist,
    ResolvedVideo,
    RetryPolicy,
    SqlEventRecorder,
    UnavailableError,
    UnsupportedUrlError,
    YtDlpGateway,
    create_gateway,
)
from homefeed_core.gateway.normalize import (
    featured_channels_from_info,
    pick_caption_track,
    related_from_info,
)
from homefeed_core.gateway.ytdlp import ExtractRequest, classify_error

VERITASIUM = "UCHnyfMqiRRG1u-2MsSQLbXA"
NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)


class Harness:
    def __init__(self, extract: Callable[[ExtractRequest], dict[str, Any]]) -> None:
        self.recorder = MemoryEventRecorder()
        self.sleeps: list[float] = []
        self.gateway = YtDlpGateway(
            recorder=self.recorder,
            retry=RetryPolicy(attempts=3, initial_delay=1.0, multiplier=2.0, jitter=0.0),
            rate_limiter=RateLimiter(0.0),
            extract=extract,
            sleep=self.sleeps.append,
            now=lambda: NOW,
        )


@pytest.fixture
def replay() -> Replay:
    return Replay()


@pytest.fixture
def harness(replay: Replay) -> Harness:
    return Harness(replay)


def test_implements_gateway_protocol(harness: Harness) -> None:
    gateway: Gateway = harness.gateway
    assert gateway is harness.gateway


# get_video


def test_get_video_normalizes_metadata(harness: Harness) -> None:
    video = harness.gateway.get_video("jNQXAC9IVRw")

    assert video.id == "jNQXAC9IVRw"
    assert video.title == "Me at the zoo"
    assert video.channel_id == "UC4QobU6STFB0P71PMvOGN5A"
    assert video.channel_title == "jawed"
    assert video.channel_handle == "@jawed"
    assert video.duration_seconds == 19
    assert video.published_at == datetime(2005, 4, 24, 3, 31, 52, tzinfo=UTC)
    assert video.live_status == "not_live"
    assert video.is_short is False
    assert video.view_count is not None and video.view_count > 300_000_000
    assert video.thumbnail_url is not None and video.thumbnail_url.startswith("https://i.ytimg")
    assert video.description and "00:05 The cool thing" in video.description
    assert video.chapters == (
        Chapter("Intro", 0, 5),
        Chapter("The cool thing", 5, 17),
        Chapter("End", 17, 19),
    )


def test_get_video_long_video_with_chapters(harness: Harness) -> None:
    video = harness.gateway.get_video("NiCgcUTL9_Q")

    assert video.channel_id == VERITASIUM
    assert video.channel_handle == "@veritasium"
    assert video.duration_seconds == 2072
    assert video.is_short is False
    assert video.tags
    for chapter in video.chapters:
        assert 0 <= chapter.start_seconds < chapter.end_seconds <= 2072


def test_get_video_detects_shorts(harness: Harness) -> None:
    video = harness.gateway.get_video("j9p3Sn8ROL4")

    assert video.is_short is True


def test_get_video_unavailable(harness: Harness) -> None:
    with pytest.raises(UnavailableError, match="unavailable"):
        harness.gateway.get_video("xxxxxxxxxxx")

    [event] = harness.recorder.events
    assert (event.operation, event.target, event.success) == ("get_video", "xxxxxxxxxxx", False)
    assert event.error_kind == "unavailable"
    assert harness.sleeps == []  # not retried


def test_get_video_rejects_malformed_id_without_extracting(
    harness: Harness, replay: Replay
) -> None:
    with pytest.raises(UnavailableError):
        harness.gateway.get_video("not an id")
    assert replay.requests == []


# get_captions


def test_get_captions_uploaded_track(harness: Harness, replay: Replay) -> None:
    captions = harness.gateway.get_captions("jNQXAC9IVRw")

    assert replay.requests == [
        ExtractRequest("https://www.youtube.com/watch?v=jNQXAC9IVRw", captions=True)
    ]
    assert captions is not None
    assert (captions.video_id, captions.language, captions.is_automatic) == (
        "jNQXAC9IVRw",
        "en",
        False,
    )
    assert captions.segments[0] == CaptionSegment(
        1.2, 3.36, "All right, so here we are, in front of the elephants"
    )
    assert captions.text().endswith("and that's pretty much all there is to say")
    [event] = harness.recorder.events
    assert (event.operation, event.target, event.success) == ("get_captions", "jNQXAC9IVRw", True)


def test_get_captions_text_can_stop_early(harness: Harness) -> None:
    captions = harness.gateway.get_captions("NiCgcUTL9_Q")

    assert captions is not None
    assert captions.text().startswith("- In 1887, a young physics teacher attached a thin glass")
    excerpt = captions.text(until_seconds=60)
    assert len(excerpt) < len(captions.text(until_seconds=300)) < len(captions.text())
    starts = [segment.start_seconds for segment in captions.segments]
    assert starts == sorted(starts)


def test_get_captions_joins_automatic_word_pieces(harness: Harness) -> None:
    captions = harness.gateway.get_captions("j9p3Sn8ROL4")

    assert captions is not None
    assert (captions.language, captions.is_automatic) == ("en-orig", True)
    assert captions.segments[0].text == "Okay, so you can see we're getting a"
    # Newline-only and styling events are dropped.
    assert all(segment.text.strip() for segment in captions.segments)


def test_get_captions_none_when_the_video_has_none(harness: Harness) -> None:
    assert harness.gateway.get_captions("hY7m5jjJ9mM") is None
    assert harness.recorder.events[0].success is True


def test_get_captions_unavailable_video(harness: Harness) -> None:
    with pytest.raises(UnavailableError):
        harness.gateway.get_captions("xxxxxxxxxxx")

    [event] = harness.recorder.events
    assert (event.operation, event.success, event.error_kind) == (
        "get_captions",
        False,
        "unavailable",
    )


def test_get_captions_rejects_malformed_id_without_extracting(
    harness: Harness, replay: Replay
) -> None:
    with pytest.raises(UnavailableError):
        harness.gateway.get_captions("not an id")
    assert replay.requests == []


def tracks(*languages: str) -> dict[str, list[dict[str, str]]]:
    return {
        lang: [
            {"ext": "srv1", "url": f"https://example.invalid/{lang}.srv1"},
            {"ext": "json3", "url": f"https://example.invalid/{lang}.json3"},
        ]
        for lang in languages
    }


@pytest.mark.parametrize(
    ("info", "expected"),
    [
        # Uploaded English beats everything; exact "en" beats regional variants.
        (
            {"subtitles": tracks("de", "en-GB", "en"), "automatic_captions": tracks("en-orig")},
            ("en", False),
        ),
        ({"subtitles": tracks("en-US"), "automatic_captions": tracks("en-orig")}, ("en-US", False)),
        # Then automatic English: original speech before translation.
        (
            {"subtitles": tracks("de"), "automatic_captions": tracks("en", "en-orig")},
            ("en-orig", True),
        ),
        (
            {
                "language": "de",
                "subtitles": tracks("fr", "de"),
                "automatic_captions": tracks("en", "de-orig"),
            },
            ("en", True),
        ),
        # Then uploaded captions, in the video's language first.
        (
            {
                "language": "de",
                "subtitles": tracks("fr", "de-DE"),
                "automatic_captions": tracks("de-orig"),
            },
            ("de-DE", False),
        ),
        ({"subtitles": tracks("fr"), "automatic_captions": tracks("de-orig")}, ("fr", False)),
        ({"automatic_captions": tracks("ko", "ko-orig")}, ("ko-orig", True)),
        # Live chat replays and tracks without json3 don't count.
        (
            {
                "subtitles": {
                    "live_chat": [{"ext": "json3", "url": "x"}],
                    "en": [{"ext": "vtt", "url": "y"}],
                }
            },
            None,
        ),
        ({}, None),
    ],
)
def test_pick_caption_track(info: dict[str, Any], expected: tuple[str, bool] | None) -> None:
    track = pick_caption_track(info)

    assert (track and (track.language, track.is_automatic)) == expected
    if track is not None:
        assert track.url.endswith(".json3")


# get_formats


def test_get_formats_normalizes_streams(harness: Harness) -> None:
    formats = harness.gateway.get_formats("jNQXAC9IVRw")
    by_itag = {f.itag: f for f in formats}

    audio = by_itag["140"]
    assert audio.kind == "audio"
    assert audio.protocol == "https"
    assert audio.mime_type == "audio/mp4"
    assert audio.codecs == "mp4a.40.2"
    assert audio.audio_sample_rate == 44100
    assert audio.audio_channels == 2
    assert audio.bitrate is not None and audio.bitrate > 100_000
    assert audio.filesize is not None and audio.filesize > 0
    assert audio.expires_at is not None and audio.expires_at.tzinfo is UTC
    assert audio.http_headers.get("User-Agent")

    video = by_itag["134"]
    assert (video.kind, video.mime_type, video.width, video.height) == (
        "video",
        "video/mp4",
        320,
        240,
    )
    assert video.codecs.startswith("avc1")

    assert by_itag["140-drc"].is_drc
    assert by_itag["251"].mime_type == "audio/webm"
    assert by_itag["233"].kind == "audio"  # HLS audio, reported without an acodec


def test_get_formats_drops_storyboards_and_keeps_every_url(harness: Harness) -> None:
    for video_id in ("jNQXAC9IVRw", "NiCgcUTL9_Q", "j9p3Sn8ROL4"):
        formats = harness.gateway.get_formats(video_id)
        assert formats
        assert all(f.url.startswith("https://") for f in formats)
        assert not any(f.protocol == "mhtml" for f in formats)
        assert {"audio", "video"} <= {f.kind for f in formats}


def test_fixtures_do_not_contain_the_recording_ip(harness: Harness) -> None:
    for fmt in harness.gateway.get_formats("NiCgcUTL9_Q"):
        if "ip=" in fmt.url:
            assert "ip=203.0.113.1" in fmt.url


# get_related


def test_get_related(harness: Harness, replay: Replay) -> None:
    related = harness.gateway.get_related("NiCgcUTL9_Q")

    assert replay.requests == [
        ExtractRequest("https://www.youtube.com/watch?v=NiCgcUTL9_Q", related=True)
    ]
    first = related[0]
    assert (first.id, first.title) == (
        "cKnwkxItL2M",
        "Inside America's Only Internet Sea Cable Maker",
    )
    assert (first.channel_id, first.channel_title, first.channel_handle) == (
        "UCcyq283he07B7_KUX07mmtA",
        "Business Insider",
        "@BusinessInsider",
    )
    assert (first.duration_seconds, first.view_count) == (900, 2_800_000)
    assert first.thumbnail_url is not None and "cKnwkxItL2M" in first.thumbnail_url
    # One of the 20 suggestions came without a channel id and is left out.
    assert len(related) == 19
    assert "GTUjzePurZ0" not in {video.id for video in related}
    assert all(video.channel_id.startswith("UC") for video in related)
    assert len({video.id for video in related}) == 19
    [event] = harness.recorder.events
    assert (event.operation, event.target, event.success) == ("get_related", "NiCgcUTL9_Q", True)


def test_get_related_limit(harness: Harness) -> None:
    related = harness.gateway.get_related("jNQXAC9IVRw", limit=3)

    assert [video.id for video in related] == [
        video.id for video in harness.gateway.get_related("jNQXAC9IVRw")[:3]
    ]


def test_get_related_unavailable_video(harness: Harness) -> None:
    with pytest.raises(UnavailableError, match="isn't available"):
        harness.gateway.get_related("xxxxxxxxxxx")

    [event] = harness.recorder.events
    assert (event.operation, event.success, event.error_kind) == (
        "get_related",
        False,
        "unavailable",
    )


def test_get_related_rejects_bad_input(harness: Harness, replay: Replay) -> None:
    with pytest.raises(UnavailableError):
        harness.gateway.get_related("not an id")
    with pytest.raises(ValueError):
        harness.gateway.get_related("jNQXAC9IVRw", limit=0)
    assert replay.requests == []


def test_related_from_info_skips_the_seed_duplicates_and_incomplete_entries() -> None:
    entry = {"id": "aaaaaaaaaaa", "title": "A", "channel_id": VERITASIUM, "channel": "V"}
    related = related_from_info(
        {
            "id": "sssssssssss",
            "entries": [
                {**entry, "id": "sssssssssss"},
                entry,
                entry,
                {**entry, "id": "bbbbbbbbbbb", "channel_id": None},
                {**entry, "id": "ccccccccccc", "title": None},
                "junk",
                {**entry, "id": "ddddddddddd", "live_status": "is_live"},
            ],
        }
    )

    assert [(video.id, video.live_status) for video in related] == [
        ("aaaaaaaaaaa", None),
        ("ddddddddddd", "is_live"),
    ]


# get_featured_channels


def test_get_featured_channels(harness: Harness, replay: Replay) -> None:
    featured = harness.gateway.get_featured_channels(VERITASIUM)

    assert replay.requests == [
        ExtractRequest(f"https://www.youtube.com/channel/{VERITASIUM}", featured=True)
    ]
    assert len(featured) == 12
    first = featured[0]
    assert (first.id, first.title, first.handle) == (
        "UCin0m13qWv3-051xlWlHamA",
        "Veritasium en Français",
        "@VeritasiumFR",
    )
    assert first.url == "https://www.youtube.com/channel/UCin0m13qWv3-051xlWlHamA"
    assert (first.subscriber_count, first.video_count) == (29_900, 178)
    assert first.thumbnail_url is not None
    assert first.thumbnail_url.startswith("https://yt3.googleusercontent.com/")
    assert "=s176-" in first.thumbnail_url  # the largest one
    assert "UCwpHKudUkP5tNgmMdexB3ow" in {channel.id for channel in featured}  # Mentour Pilot
    [event] = harness.recorder.events
    assert (event.operation, event.target, event.success) == (
        "get_featured_channels",
        VERITASIUM,
        True,
    )


def test_get_featured_channels_drops_duplicates(harness: Harness) -> None:
    featured = harness.gateway.get_featured_channels("UC4QobU6STFB0P71PMvOGN5A")

    ids = [channel.id for channel in featured]
    assert ids[:2] == ["UCPszuZ3hR89D4NqFd7g3mDQ", "UCC5NfQ6Mf0dq_eEwv4P_hWA"]
    assert ids.count("UCPszuZ3hR89D4NqFd7g3mDQ") == 1  # featured twice
    assert len(ids) == 10
    assert featured[0].video_count is None  # no video count shown


def test_get_featured_channels_none(harness: Harness) -> None:
    assert harness.gateway.get_featured_channels("UCin0m13qWv3-051xlWlHamA") == []


def test_get_featured_channels_missing_channel(harness: Harness) -> None:
    with pytest.raises(UnavailableError, match="does not exist"):
        harness.gateway.get_featured_channels("UCxxxxxxxxxxxxxxxxxxxxxx")

    [event] = harness.recorder.events
    assert (event.operation, event.success, event.error_kind) == (
        "get_featured_channels",
        False,
        "unavailable",
    )
    assert harness.sleeps == []  # not retried


def test_get_featured_channels_rejects_bad_input(harness: Harness, replay: Replay) -> None:
    with pytest.raises(UnavailableError):
        harness.gateway.get_featured_channels("@veritasium")
    assert replay.requests == []


def test_featured_channels_from_info_skips_the_owner_duplicates_and_bad_ids() -> None:
    entry = {"id": "UC" + "a" * 22, "title": "A", "uploader_id": "@a"}
    featured = featured_channels_from_info(
        {
            "id": VERITASIUM,
            "entries": [
                {**entry, "id": VERITASIUM},
                entry,
                entry,
                {**entry, "id": "not a channel"},
                {**entry, "id": None},
                "junk",
                {"id": "UC" + "b" * 22, "uploader_id": "not a handle"},
            ],
        }
    )

    assert [(channel.id, channel.title, channel.handle) for channel in featured] == [
        ("UC" + "a" * 22, "A", "@a"),
        ("UC" + "b" * 22, "", None),
    ]


# get_channel_uploads


def test_get_channel_uploads(harness: Harness, replay: Replay) -> None:
    uploads = harness.gateway.get_channel_uploads(VERITASIUM, limit=5)

    assert replay.requests == [
        ExtractRequest(f"https://www.youtube.com/channel/{VERITASIUM}/videos", True, 5)
    ]
    channel = uploads.channel
    assert channel.id == VERITASIUM
    assert channel.title == "Veritasium"
    assert channel.handle == "@veritasium"
    assert channel.url == f"https://www.youtube.com/channel/{VERITASIUM}"
    assert channel.thumbnail_url is not None
    assert len(uploads.videos) == 5
    first = uploads.videos[0]
    assert first.id == "NiCgcUTL9_Q"
    assert first.title == "How We Trapped Light and Built the Internet"
    assert first.duration_seconds == 2072
    assert first.thumbnail_url is not None
    assert len({v.id for v in uploads.videos}) == 5


def test_get_channel_uploads_missing_channel(harness: Harness) -> None:
    with pytest.raises(UnavailableError, match="does not exist"):
        harness.gateway.get_channel_uploads("UCxxxxxxxxxxxxxxxxxxxxxx", limit=5)

    [event] = harness.recorder.events
    assert (event.operation, event.success, event.error_kind) == (
        "get_channel_uploads",
        False,
        "unavailable",
    )


def test_get_channel_uploads_rejects_bad_input(harness: Harness, replay: Replay) -> None:
    with pytest.raises(UnavailableError):
        harness.gateway.get_channel_uploads("@veritasium")
    with pytest.raises(ValueError):
        harness.gateway.get_channel_uploads(VERITASIUM, limit=0)
    assert replay.requests == []


# resolve_url


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/@veritasium",
        "youtube.com/@veritasium/featured",
        "@veritasium",
        "https://www.youtube.com/user/1veritasium",
        f"https://m.youtube.com/channel/{VERITASIUM}/videos",
    ],
)
def test_resolve_channel_urls_to_canonical_channel(harness: Harness, url: str) -> None:
    replay = Replay()
    replay.records[
        ExtractRequest(f"https://www.youtube.com/channel/{VERITASIUM}/videos", True, 1)
    ] = replay.records[ExtractRequest("https://www.youtube.com/@veritasium/videos", True, 1)]
    gateway = Harness(replay).gateway

    resolved = gateway.resolve_url(url)

    assert isinstance(resolved, ResolvedChannel)
    assert resolved.channel.id == VERITASIUM
    assert resolved.channel.title == "Veritasium"
    assert resolved.channel.handle == "@veritasium"


def test_resolve_video_url_needs_no_extraction(harness: Harness, replay: Replay) -> None:
    resolved = harness.gateway.resolve_url("https://youtu.be/jNQXAC9IVRw?t=1m5s")

    assert resolved == ResolvedVideo("jNQXAC9IVRw", start_seconds=65)
    assert replay.requests == []
    assert harness.recorder.events == []


def test_resolve_playlist_url(harness: Harness) -> None:
    resolved = harness.gateway.resolve_url(
        "https://www.youtube.com/playlist?list=PLFs4vir_WsTwEd-nJgVJCZPNL3HALHHpF"
    )
    assert resolved == ResolvedPlaylist("PLFs4vir_WsTwEd-nJgVJCZPNL3HALHHpF")


def test_resolve_rejects_other_urls(harness: Harness) -> None:
    with pytest.raises(UnsupportedUrlError):
        harness.gateway.resolve_url("https://vimeo.com/12345")


# Retries, rate limiting, recording


class Flaky:
    """Fails with each of `errors` in turn, then replays the fixture."""

    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.calls = 0
        self.replay = Replay()

    def __call__(self, request: ExtractRequest) -> dict[str, Any]:
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return self.replay(request)


def test_transient_failures_are_retried_with_backoff() -> None:
    extract = Flaky(ExtractionError("timed out"), RateLimitedError("HTTP Error 429"))
    harness = Harness(extract)

    video = harness.gateway.get_video("jNQXAC9IVRw")

    assert video.title == "Me at the zoo"
    assert extract.calls == 3
    assert harness.sleeps == [1.0, 2.0]
    [event] = harness.recorder.events
    assert event.success is True
    assert event.attempts == 3
    assert event.at == NOW
    assert event.error is None


def test_gives_up_after_the_last_attempt_and_records_the_failure() -> None:
    extract = Flaky(*(ExtractionError(f"boom {n}") for n in range(5)))
    harness = Harness(extract)

    with pytest.raises(ExtractionError, match="boom 2"):
        harness.gateway.get_video("jNQXAC9IVRw")

    assert extract.calls == 3
    [event] = harness.recorder.events
    assert (event.success, event.attempts, event.error_kind, event.error) == (
        False,
        3,
        "extraction",
        "boom 2",
    )


def test_unexpected_response_is_an_extraction_error() -> None:
    harness = Harness(lambda _request: {"id": "jNQXAC9IVRw"})  # no title, no channel

    with pytest.raises(ExtractionError, match="missing"):
        harness.gateway.get_video("jNQXAC9IVRw")
    assert harness.recorder.events[0].error_kind == "extraction"


def test_rate_limiter_spaces_calls() -> None:
    now = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(2.0, clock=lambda: now[0], sleep=sleep)

    limiter.wait()
    now[0] += 0.5
    limiter.wait()
    now[0] += 5.0
    limiter.wait()

    assert sleeps == [1.5]


def test_gateway_waits_on_the_rate_limiter_for_every_attempt() -> None:
    waits: list[str] = []

    class CountingLimiter(RateLimiter):
        def wait(self) -> None:
            waits.append("wait")

    gateway = YtDlpGateway(
        rate_limiter=CountingLimiter(),
        retry=RetryPolicy(attempts=2, jitter=0.0),
        extract=Flaky(ExtractionError("once")),
        sleep=lambda _s: None,
    )
    gateway.get_video("jNQXAC9IVRw")

    assert waits == ["wait", "wait"]


def test_retry_delay_grows_and_is_capped() -> None:
    import random

    policy = RetryPolicy(initial_delay=2.0, multiplier=3.0, max_delay=10.0, jitter=0.5)
    rng = random.Random(0)

    delays = [policy.delay(n, rng) for n in (1, 2, 3, 4)]

    assert 2.0 <= delays[0] <= 3.0
    assert 6.0 <= delays[1] <= 9.0
    assert 10.0 <= delays[2] <= 15.0
    assert 10.0 <= delays[3] <= 15.0


@pytest.mark.parametrize(
    ("message", "kind"),
    [
        ("ERROR: [youtube] abc: Video unavailable", "unavailable"),
        (
            "ERROR: [youtube] abc: Private video. Sign in if you've been granted access",
            "unavailable",
        ),
        ("ERROR: [youtube] abc: Sign in to confirm your age", "unavailable"),
        ("ERROR: [youtube] abc: This live event will begin in 3 hours.", "unavailable"),
        ("ERROR: [youtube:tab] @x: This channel does not have a videos tab", "unavailable"),
        ("ERROR: Unable to download webpage: HTTP Error 429: Too Many Requests", "rate_limited"),
        ("ERROR: [youtube] abc: Sign in to confirm you’re not a bot", "rate_limited"),
        ("ERROR: Unable to download webpage: <urlopen error timed out>", "extraction"),
        ("ERROR: [youtube] abc: Failed to extract any player response", "extraction"),
    ],
)
def test_classify_error(message: str, kind: str) -> None:
    error = classify_error(message)
    assert error.kind == kind
    assert not str(error).startswith("ERROR:")


# Recording into extractor_events


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def test_failures_are_recorded_in_extractor_events(
    sessions: sessionmaker[Session], replay: Replay
) -> None:
    gateway = YtDlpGateway(
        recorder=SqlEventRecorder(sessions),
        rate_limiter=RateLimiter(0.0),
        extract=replay,
        now=lambda: NOW,
    )

    gateway.get_video("jNQXAC9IVRw")
    with pytest.raises(UnavailableError):
        gateway.get_video("xxxxxxxxxxx")

    with sessions() as session:
        rows = session.execute(
            text(
                "SELECT operation, target, success, error_kind, error, attempts, at "
                "FROM extractor_events ORDER BY id"
            )
        ).all()
    assert [tuple(row) for row in rows] == [
        ("get_video", "jNQXAC9IVRw", 1, None, None, 1, "2026-10-12T06:00:00.000Z"),
        (
            "get_video",
            "xxxxxxxxxxx",
            0,
            "unavailable",
            "[youtube] xxxxxxxxxxx: This video is unavailable",
            1,
            "2026-10-12T06:00:00.000Z",
        ),
    ]


def test_recording_failure_does_not_break_the_call(
    tmp_path: Path, replay: Replay, caplog: pytest.LogCaptureFixture
) -> None:
    sessions = open_database(tmp_path / "homefeed.sqlite")
    bind = sessions.kw["bind"]
    assert isinstance(bind, Engine)
    with sessions.begin() as session:
        session.execute(text("DROP TABLE extractor_events"))
    gateway = YtDlpGateway(
        recorder=SqlEventRecorder(sessions), rate_limiter=RateLimiter(0.0), extract=replay
    )

    assert gateway.get_video("jNQXAC9IVRw").title == "Me at the zoo"
    assert "Could not record extractor event" in caplog.text
    bind.dispose()


def test_create_gateway_records_into_the_database(sessions: sessionmaker[Session]) -> None:
    gateway = create_gateway(sessions)
    assert isinstance(gateway, YtDlpGateway)


# The real yt-dlp path


@pytest.mark.skipif(LIVE_TESTS, reason="needs the network to be blocked")
def test_real_extractor_errors_become_gateway_errors() -> None:
    """With the network blocked, yt-dlp fails and the Gateway reports an ExtractionError."""
    recorder = MemoryEventRecorder()
    gateway = YtDlpGateway(
        recorder=recorder, retry=RetryPolicy(attempts=1), rate_limiter=RateLimiter(0.0)
    )

    with pytest.raises(ExtractionError):
        gateway.get_video("jNQXAC9IVRw")
    assert recorder.events[0].success is False


@pytest.mark.skipif(not LIVE_TESTS, reason="live smoke test; set HOMEFEED_LIVE_TESTS=1")
def test_live_smoke() -> None:
    gateway = YtDlpGateway(rate_limiter=RateLimiter(1.0))

    assert gateway.get_video("jNQXAC9IVRw").title == "Me at the zoo"
    assert any(f.kind == "audio" for f in gateway.get_formats("jNQXAC9IVRw"))
    assert gateway.get_channel_uploads(VERITASIUM, limit=3).videos
    captions = gateway.get_captions("jNQXAC9IVRw")
    assert captions is not None and "elephants" in captions.text()
    assert gateway.get_related("jNQXAC9IVRw", limit=5)
    assert gateway.get_featured_channels(VERITASIUM)
    resolved = gateway.resolve_url("https://www.youtube.com/@veritasium")
    assert isinstance(resolved, ResolvedChannel) and resolved.channel.id == VERITASIUM
