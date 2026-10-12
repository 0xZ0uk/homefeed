import json
import xml.etree.ElementTree as ET
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from gateway_fixtures import FIXTURES
from media_samples import mp4, mp4_ranges, webm, webm_ranges

from homefeed_core.gateway import ByteRange, Format, MediaUrlExpiredError, UnavailableError
from homefeed_core.gateway.fake import FakeGateway, make_format, make_video
from homefeed_core.gateway.normalize import formats_from_info, video_from_info
from homefeed_core.playback import (
    NoPlayableStreamsError,
    Playback,
    RangeNotSatisfiable,
    StreamChangedError,
    StreamNotFoundError,
    select_streams,
)

VIDEO = "aaaaaaaaaaa"
NS = {"d": "urn:mpeg:dash:schema:mpd:2011"}
NOW = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
EXPIRES = NOW + timedelta(hours=6)


def stream_url(format_id: str, *, lmt: str = "1", n: int = 0) -> str:
    return (
        f"https://rr1.googlevideo.invalid/videoplayback?itag={format_id}&lmt={lmt}"
        f"&expire={int(EXPIRES.timestamp())}&n={n}"
    )


def video_format(format_id: str = "137", **fields: Any) -> Format:
    data = mp4()
    defaults: dict[str, Any] = {
        "kind": "video",
        "url": stream_url(format_id),
        "mime_type": "video/mp4",
        "codecs": "avc1.640028",
        "width": 1920,
        "height": 1080,
        "fps": 30.0,
        "bitrate": 2_000_000,
        "filesize": len(data),
        "expires_at": EXPIRES,
        "init_range": mp4_ranges()[0],
        "index_range": mp4_ranges()[1],
    }
    return make_format(format_id, **(defaults | fields))


def audio_format(format_id: str = "140", **fields: Any) -> Format:
    defaults: dict[str, Any] = {
        "url": stream_url(format_id),
        "filesize": len(mp4()),
        "audio_sample_rate": 44100,
        "audio_channels": 2,
        "expires_at": EXPIRES,
        "init_range": mp4_ranges()[0],
        "index_range": mp4_ranges()[1],
    }
    return make_format(format_id, **(defaults | fields))


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def setup(*formats: Format, chunk_bytes: int = 4096) -> tuple[FakeGateway, Playback, Clock]:
    gateway = FakeGateway()
    gateway.add_video(make_video(VIDEO, duration_seconds=212), formats)
    for fmt in formats:
        gateway.add_media(fmt.url, mp4())
    clock = Clock()
    return gateway, Playback(gateway, now=clock, chunk_bytes=chunk_bytes), clock


def representations(mpd: str) -> dict[str, ET.Element]:
    root = ET.fromstring(mpd)
    return {r.attrib["id"]: r for r in root.iterfind(".//d:Representation", NS)}


# Manifest


def test_manifest_lists_streams_with_segment_base_and_proxy_urls() -> None:
    _, playback, _ = setup(video_format(), audio_format())
    mpd = playback.manifest(VIDEO)
    root = ET.fromstring(mpd)

    assert root.attrib["type"] == "static"
    assert root.attrib["mediaPresentationDuration"] == "PT212S"
    assert "googlevideo" not in mpd
    reps = representations(mpd)
    assert set(reps) == {"137", "140"}
    video = reps["137"]
    assert video.attrib == {
        "id": "137",
        "codecs": "avc1.640028",
        "bandwidth": "2000000",
        "width": "1920",
        "height": "1080",
        "frameRate": "30",
    }
    assert video.findtext("d:BaseURL", namespaces=NS) == "media/137"
    segment_base = video.find("d:SegmentBase", NS)
    assert segment_base is not None
    init, index = mp4_ranges()
    assert segment_base.attrib["indexRange"] == str(index)
    initialization = segment_base.find("d:Initialization", NS)
    assert initialization is not None and initialization.attrib["range"] == str(init)
    audio = reps["140"]
    assert audio.attrib["audioSamplingRate"] == "44100"
    channels = audio.find("d:AudioChannelConfiguration", NS)
    assert channels is not None and channels.attrib["value"] == "2"


def test_manifest_groups_by_container_and_codec() -> None:
    formats = [
        video_format("137"),
        video_format("136", height=720, bitrate=1_000_000),
        video_format("399", codecs="av01.0.08M.08"),
        video_format("248", mime_type="video/webm", codecs="vp9"),
        audio_format("140"),
        audio_format("251", mime_type="audio/webm", codecs="opus"),
    ]
    _, playback, _ = setup(*formats)
    root = ET.fromstring(playback.manifest(VIDEO))
    sets = [
        (
            s.attrib["contentType"],
            s.attrib["mimeType"],
            [r.attrib["id"] for r in s.iterfind("d:Representation", NS)],
        )
        for s in root.iterfind(".//d:AdaptationSet", NS)
    ]
    assert sets == [
        ("video", "video/mp4", ["399"]),
        ("video", "video/mp4", ["136", "137"]),  # avc1, by bandwidth
        ("video", "video/webm", ["248"]),
        ("audio", "audio/mp4", ["140"]),
        ("audio", "audio/webm", ["251"]),
    ]


def test_select_streams_drops_hls_drc_and_dubbed_audio() -> None:
    formats = [
        video_format("137"),
        video_format("270", protocol="m3u8_native"),
        make_format("18", kind="muxed", mime_type="video/mp4", codecs="avc1, mp4a.40.2"),
        audio_format("140-drc", is_drc=True, language="en"),
        audio_format("140-0", language="en", note="English original (default), medium"),
        audio_format("140-1", language="de", note="German, medium"),
        audio_format("140-2", language="fr", note="French, medium"),
    ]
    assert [f.itag for f in select_streams(formats)] == ["137", "140-0"]


def test_select_streams_without_language_hints_keeps_the_most_common() -> None:
    formats = [
        audio_format("140-0", language="en"),
        audio_format("251-0", language="en", mime_type="audio/webm", codecs="opus"),
        audio_format("140-1", language="de"),
    ]
    assert [f.itag for f in select_streams(formats)] == ["140-0", "251-0"]


def test_manifest_probes_streams_without_ranges_and_omits_failures() -> None:
    no_ranges: dict[str, Any] = {"init_range": None, "index_range": None}
    webm_audio = audio_format("251", mime_type="audio/webm", codecs="opus", **no_ranges)
    broken = video_format("248", mime_type="video/webm", codecs="vp9", **no_ranges)
    gateway, playback, _ = setup(video_format(), webm_audio, broken)
    gateway.add_media(webm_audio.url, webm())
    gateway.fail("probe_dash_ranges", broken.url, MediaUrlExpiredError("403"))

    reps = representations(playback.manifest(VIDEO))

    assert set(reps) == {"137", "251"}
    segment_base = reps["251"].find("d:SegmentBase", NS)
    assert segment_base is not None
    assert segment_base.attrib["indexRange"] == str(webm_ranges()[1])
    # A probe result is cached per file; failures are retried next time.
    playback.manifest(VIDEO)
    probes = [target for op, target in gateway.calls if op == "probe_dash_ranges"]
    assert probes.count(webm_audio.url) == 1
    assert probes.count(broken.url) == 2


def test_manifest_without_adaptive_streams_is_an_error() -> None:
    _, playback, _ = setup(video_format("270", protocol="m3u8_native"), audio_format())
    with pytest.raises(NoPlayableStreamsError):
        playback.manifest(VIDEO)


def test_manifest_of_an_unavailable_video_raises_the_gateway_error() -> None:
    playback = Playback(FakeGateway())
    with pytest.raises(UnavailableError):
        playback.manifest(VIDEO)


def test_manifest_and_metadata_are_cached() -> None:
    gateway, playback, _ = setup(video_format(), audio_format())
    playback.video(VIDEO)
    playback.manifest(VIDEO)
    playback.manifest(VIDEO)
    assert gateway.calls == [("get_video", VIDEO), ("get_formats", VIDEO)]


def test_manifest_from_a_recorded_response() -> None:
    record = json.loads((FIXTURES / "video_short.json").read_text())["response"]
    gateway = FakeGateway()
    gateway.add_video(video_from_info(record), formats_from_info(record))
    mpd = Playback(gateway).manifest(record["id"])

    reps = representations(mpd)
    assert {"137", "140", "248", "251", "399"} <= set(reps)
    assert not {"140-drc", "251-drc", "270", "616"} & set(reps)
    assert "googlevideo" not in mpd
    segment_base = reps["137"].find("d:SegmentBase", NS)
    assert segment_base is not None and segment_base.attrib["indexRange"] == "742-929"


# Media proxy


def body(playback: Playback, range_header: str | None, format_id: str = "137") -> bytes:
    return b"".join(playback.proxy_range(VIDEO, format_id, range_header).body)


def test_proxy_serves_a_range() -> None:
    _, playback, _ = setup(video_format())
    response = playback.proxy_range(VIDEO, "137", "bytes=100-199")
    assert response.status == 206
    assert response.content_type == "video/mp4"
    assert response.content_length == 100
    assert response.content_range == f"bytes 100-199/{len(mp4())}"
    assert b"".join(response.body) == mp4()[100:200]


def test_proxy_open_ended_suffix_and_clamped_ranges() -> None:
    _, playback, _ = setup(video_format())
    data = mp4()
    assert body(playback, "bytes=1000-") == data[1000:]
    assert body(playback, "bytes=-10") == data[-10:]
    response = playback.proxy_range(VIDEO, "137", f"bytes=10-{len(data) + 500}")
    assert response.content_range == f"bytes 10-{len(data) - 1}/{len(data)}"
    assert b"".join(response.body) == data[10:]


def test_proxy_without_a_range_serves_the_whole_file() -> None:
    _, playback, _ = setup(video_format())
    response = playback.proxy_range(VIDEO, "137", None)
    assert (response.status, response.content_range) == (200, None)
    assert response.content_length == len(mp4())
    assert b"".join(response.body) == mp4()


def test_proxy_reads_upstream_in_bounded_chunks() -> None:
    gateway, playback, _ = setup(video_format(), chunk_bytes=1000)
    assert body(playback, "bytes=0-") == mp4()
    reads = [r for _, r in gateway.media_reads]
    assert all(r.end - r.start + 1 <= 1000 for r in reads)
    assert reads[0] == ByteRange(0, 999)
    assert reads[-1].end == len(mp4()) - 1


def test_proxy_rejects_ranges_past_the_end_and_unknown_streams() -> None:
    _, playback, _ = setup(video_format())
    with pytest.raises(RangeNotSatisfiable) as error:
        playback.proxy_range(VIDEO, "137", f"bytes={len(mp4())}-")
    assert error.value.total == len(mp4())
    with pytest.raises(StreamNotFoundError):
        playback.proxy_range(VIDEO, "999", "bytes=0-1")
    with pytest.raises(StreamNotFoundError):  # HLS isn't proxied
        setup(video_format("270", protocol="m3u8_native"))[1].proxy_range(VIDEO, "270", None)


def test_proxy_refreshes_a_refused_url() -> None:
    gateway, playback, _ = setup(video_format())
    assert body(playback, "bytes=0-9") == mp4()[:10]
    old = gateway.formats[VIDEO][0]
    new = video_format(url=stream_url("137", n=1))
    gateway.formats[VIDEO] = [new]
    gateway.add_media(new.url, mp4())
    gateway.fail("open_media", old.url, MediaUrlExpiredError("403"))

    assert body(playback, "bytes=10-19") == mp4()[10:20]
    assert gateway.calls.count(("get_formats", VIDEO)) == 2
    assert body(playback, "bytes=20-29") == mp4()[20:30]  # the new URL is cached
    assert gateway.calls.count(("get_formats", VIDEO)) == 2


def test_proxy_refreshes_urls_before_they_expire() -> None:
    gateway, playback, clock = setup(video_format())
    body(playback, "bytes=0-9")
    clock.now = EXPIRES - timedelta(minutes=29)
    body(playback, "bytes=0-9")
    assert gateway.calls.count(("get_formats", VIDEO)) == 2


def test_proxy_refuses_a_replaced_file() -> None:
    gateway, playback, _ = setup(video_format())
    body(playback, "bytes=0-9")
    old = gateway.formats[VIDEO][0]
    gateway.formats[VIDEO] = [video_format(url=stream_url("137", lmt="2"))]
    gateway.fail("open_media", old.url, MediaUrlExpiredError("403"))
    with pytest.raises(StreamChangedError):
        playback.proxy_range(VIDEO, "137", "bytes=0-9")
