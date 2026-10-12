"""DASH init/index byte ranges on `Format` (spike #13, docs/spikes/0013-dash-ranges.md)."""

import inspect
from collections.abc import Iterator
from typing import Any

import pytest
from gateway_fixtures import Replay

from homefeed_core.gateway import ByteRange, YtDlpGateway
from homefeed_core.gateway import ytdlp as ytdlp_module
from homefeed_core.gateway.normalize import add_dash_ranges, dash_ranges
from homefeed_core.gateway.resilience import RateLimiter
from homefeed_core.gateway.ytdlp import ExtractRequest, _DashRangesYoutubeIE, extract_info

# Trimmed from a real "Me at the zoo" player response: itag 140 names two files
# (regular and DRC audio) with different ranges, told apart by `lastModified`.
AAC = {
    "itag": 140,
    "initRange": {"start": "0", "end": "722"},
    "indexRange": {"start": "723", "end": "778"},
    "contentLength": "309288",
    "lastModified": "1767107011597808",
}
AAC_DRC = {
    "itag": 140,
    "initRange": {"start": "0", "end": "631"},
    "indexRange": {"start": "632", "end": "687"},
    "contentLength": "309197",
    "lastModified": "1680501255309737",
    "isDrc": True,
}
VP9 = {
    "itag": 242,
    "initRange": {"start": "0", "end": "217"},
    "indexRange": {"start": "218", "end": "267"},
    "contentLength": "293080",
    "lastModified": "1680501309294787",
}
PLAYER_RESPONSES: list[Any] = [
    {},  # yt-dlp passes the webpage's (here empty) response first
    {"streamingData": {"adaptiveFormats": [AAC, AAC_DRC, VP9], "expiresInSeconds": "21540"}},
]


def ytdlp_format(format_id: str, **query: str) -> dict[str, Any]:
    params = "&".join(f"{k}={v}" for k, v in query.items())
    return {"format_id": format_id, "url": f"https://rr1.googlevideo.com/videoplayback?{params}"}


# Recorded responses


@pytest.fixture
def gateway() -> YtDlpGateway:
    return YtDlpGateway(rate_limiter=RateLimiter(0.0), extract=Replay())


def test_formats_carry_the_ranges_youtube_reported(gateway: YtDlpGateway) -> None:
    by_itag = {f.itag: f for f in gateway.get_formats("jNQXAC9IVRw")}

    assert by_itag["140"].init_range == ByteRange(0, 722)
    assert by_itag["140"].index_range == ByteRange(723, 778)
    assert by_itag["140-drc"].init_range == ByteRange(0, 631)  # same itag, other file
    assert by_itag["242"].init_range == ByteRange(0, 217)  # webm: EBML header..Tracks
    assert by_itag["242"].index_range == ByteRange(218, 267)  # webm: Cues


def test_every_adaptive_stream_has_ranges_and_hls_has_none(gateway: YtDlpGateway) -> None:
    for video_id in ("jNQXAC9IVRw", "NiCgcUTL9_Q", "j9p3Sn8ROL4"):
        for fmt in gateway.get_formats(video_id):
            if fmt.protocol != "https":
                assert fmt.init_range is None and fmt.index_range is None
                continue
            assert fmt.init_range is not None and fmt.index_range is not None, fmt.itag
            # Header first, then the index right after it (SegmentBase layout).
            assert fmt.init_range.start == 0
            assert fmt.index_range.start == fmt.init_range.end + 1
            assert fmt.index_range.end < (fmt.filesize or 0)


def test_byte_range_formats_like_dash() -> None:
    assert str(ByteRange(723, 778)) == "723-778"


# Matching raw streams to yt-dlp formats


def test_matches_streams_by_last_modified() -> None:
    ranges = dash_ranges(PLAYER_RESPONSES)
    regular = ytdlp_format("140", lmt=AAC["lastModified"], clen=AAC["contentLength"])
    drc = ytdlp_format("140-drc", lmt=AAC_DRC["lastModified"])

    add_dash_ranges(regular, ranges)
    add_dash_ranges(drc, ranges)

    assert (regular["init_range"], regular["index_range"]) == (
        {"start": 0, "end": 722},
        {"start": 723, "end": 778},
    )
    assert drc["init_range"] == {"start": 0, "end": 631}


def test_falls_back_to_content_length() -> None:
    fmt = ytdlp_format("242", clen=VP9["contentLength"])
    add_dash_ranges(fmt, dash_ranges(PLAYER_RESPONSES))
    assert fmt["index_range"] == {"start": 218, "end": 267}


def test_ambiguous_content_length_is_not_guessed() -> None:
    twin = {**AAC_DRC, "contentLength": AAC["contentLength"], "lastModified": "1"}
    ranges = dash_ranges([{"streamingData": {"adaptiveFormats": [AAC, twin]}}])
    fmt = ytdlp_format("140", clen=AAC["contentLength"])

    add_dash_ranges(fmt, ranges)

    assert "init_range" not in fmt


def test_unknown_or_malformed_streams_are_left_alone() -> None:
    broken = {**VP9, "itag": 243, "initRange": {"start": "x", "end": "1"}}
    no_index = {**VP9, "itag": 244, "indexRange": None}
    ranges = dash_ranges([None, {"streamingData": None}, {"streamingData": {}}])
    ranges |= dash_ranges([{"streamingData": {"adaptiveFormats": [broken, no_index, "?"]}}])
    assert ranges == {}

    fmt = ytdlp_format("140", lmt="999")
    add_dash_ranges(fmt, dash_ranges(PLAYER_RESPONSES))
    assert "init_range" not in fmt


# The yt-dlp hook


def test_hook_targets_a_yt_dlp_method_that_still_exists() -> None:
    """Canary for yt-dlp upgrades: the wrapped private method keeps its shape."""
    base = _DashRangesYoutubeIE.__mro__[1]
    params = list(inspect.signature(base._extract_formats_and_subtitles).parameters)
    assert params[:3] == ["self", "video_id", "player_responses"]
    assert _DashRangesYoutubeIE.ie_key() == base.ie_key() == "Youtube"


def test_hook_copies_ranges_onto_yt_dlp_formats(monkeypatch: pytest.MonkeyPatch) -> None:
    def stock(_self: Any, _video_id: str, _responses: Any, *_args: Any) -> Iterator[Any]:
        yield ytdlp_format("140", lmt=AAC["lastModified"])
        yield ytdlp_format("999", lmt="1")
        yield {"en": []}  # yt-dlp yields the subtitles last

    base = _DashRangesYoutubeIE.__mro__[1]
    monkeypatch.setattr(base, "_extract_formats_and_subtitles", stock)
    extractor = _DashRangesYoutubeIE()

    *formats, subtitles = extractor._extract_formats_and_subtitles(
        "jNQXAC9IVRw", PLAYER_RESPONSES, None, "not_live", 19
    )

    assert formats[0]["index_range"] == {"start": 723, "end": 778}
    assert "index_range" not in formats[1]
    assert subtitles == {"en": []}


def test_extract_info_installs_the_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    installed: list[Any] = []

    class FakeYoutubeDL:
        def __init__(self, _options: Any) -> None: ...
        def __enter__(self) -> "FakeYoutubeDL":
            return self

        def __exit__(self, *_exc: Any) -> None: ...
        def add_info_extractor(self, ie: Any) -> None:
            installed.append(ie)

        def extract_info(self, _url: str, download: bool) -> dict[str, Any]:
            return {"id": "jNQXAC9IVRw"}

        def sanitize_info(self, info: dict[str, Any]) -> dict[str, Any]:
            return info

    monkeypatch.setattr(ytdlp_module.yt_dlp, "YoutubeDL", FakeYoutubeDL)

    assert extract_info(ExtractRequest("https://www.youtube.com/watch?v=jNQXAC9IVRw"))
    assert [type(ie) for ie in installed] == [_DashRangesYoutubeIE]
