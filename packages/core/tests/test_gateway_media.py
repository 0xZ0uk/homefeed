import io
import urllib.error
import urllib.request
from collections.abc import Callable
from email.message import Message
from http.client import HTTPResponse
from typing import cast

import pytest
from media_samples import box, mp4, mp4_ranges, webm, webm_ranges

from homefeed_core.gateway import (
    MAX_RANGE_BYTES,
    ByteRange,
    ExtractionError,
    Format,
    HttpMediaFetcher,
    MediaStream,
    MediaUrlExpiredError,
    MemoryEventRecorder,
    RangeNotSatisfiableError,
    UnavailableError,
    YtDlpGateway,
)
from homefeed_core.gateway.dash import dash_ranges_from_bytes, probe_dash_ranges
from homefeed_core.gateway.fake import FakeGateway, make_format, make_video

# Probe parser


def reader(data: bytes) -> tuple[Callable[[ByteRange], bytes], list[ByteRange]]:
    reads: list[ByteRange] = []

    def fetch(byte_range: ByteRange) -> bytes:
        reads.append(byte_range)
        return data[byte_range.start : byte_range.end + 1]

    return fetch, reads


def test_probe_finds_mp4_sidx_in_the_first_2kb() -> None:
    fetch, reads = reader(mp4())
    assert probe_dash_ranges(fetch) == mp4_ranges()
    assert reads == [ByteRange(0, 2047)]


def test_probe_finds_webm_cues() -> None:
    fetch, _ = reader(webm())
    assert probe_dash_ranges(fetch) == webm_ranges()


def test_probe_reads_further_when_the_header_is_large() -> None:
    fetch, reads = reader(mp4(moov_payload=5000))
    assert probe_dash_ranges(fetch) == mp4_ranges(moov_payload=5000)
    assert reads == [ByteRange(0, 2047), ByteRange(0, 65535)]


def test_probe_gives_up_on_media_before_the_index() -> None:
    no_index = box(b"ftyp", 16) + box(b"moov", 100) + box(b"moof", 50) + box(b"mdat", 3000)
    assert probe_dash_ranges(reader(no_index)[0]) is None
    assert dash_ranges_from_bytes(b"not a media file at all") is None


def test_probe_gives_up_on_a_short_file_without_index() -> None:
    fetch, reads = reader(box(b"ftyp", 16) + box(b"moov", 100))
    assert probe_dash_ranges(fetch) is None
    assert len(reads) == 1


# HTTP fetcher


class Response(io.BytesIO):
    def __init__(self, data: bytes, status: int = 206, content_range: str | None = None) -> None:
        super().__init__(data)
        self.status = status
        self.headers = Message()
        if content_range:
            self.headers["Content-Range"] = content_range


def http_fetcher(
    respond: Response | Exception,
) -> tuple[HttpMediaFetcher, list[urllib.request.Request]]:
    requests: list[urllib.request.Request] = []

    def open_url(request: urllib.request.Request, timeout: float) -> HTTPResponse:
        requests.append(request)
        if isinstance(respond, Exception):
            raise respond
        return cast(HTTPResponse, respond)

    return HttpMediaFetcher(open_url=open_url), requests


def http_error(status: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://x.invalid", status, "error", Message(), None)


def test_fetcher_sends_a_range_and_the_format_headers() -> None:
    fmt = make_format("137", http_headers={"User-Agent": "test-agent"})
    fetcher, requests = http_fetcher(Response(b"abcd", content_range="bytes 10-13/100"))

    with fetcher(fmt, ByteRange(10, 13)) as stream:
        assert stream.read() == b"abcd"
        assert stream.byte_range == ByteRange(10, 13)
        assert stream.total == 100

    assert requests[0].full_url == fmt.url
    assert requests[0].get_header("Range") == "bytes=10-13"
    assert requests[0].get_header("User-agent") == "test-agent"


def test_fetcher_refuses_unranged_and_oversized_reads() -> None:
    fmt = make_format()
    with pytest.raises(ValueError):
        http_fetcher(Response(b""))[0](fmt, ByteRange(0, MAX_RANGE_BYTES))
    with pytest.raises(ExtractionError, match="206"):
        http_fetcher(Response(b"whole file", status=200))[0](fmt, ByteRange(0, 9))
    with pytest.raises(ExtractionError, match="Asked for"):
        http_fetcher(Response(b"x", content_range="bytes 5-5/10"))[0](fmt, ByteRange(0, 0))


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (403, MediaUrlExpiredError),
        (410, MediaUrlExpiredError),
        (404, UnavailableError),
        (416, RangeNotSatisfiableError),
        (500, ExtractionError),
    ],
)
def test_fetcher_maps_http_errors(status: int, error: type[Exception]) -> None:
    with pytest.raises(error):
        http_fetcher(http_error(status))[0](make_format(), ByteRange(0, 9))


def test_ytdlp_gateway_records_media_failures_and_probes() -> None:
    data = mp4()
    recorder = MemoryEventRecorder()

    def media(fmt: Format, byte_range: ByteRange) -> MediaStream:
        if byte_range.start > 0:
            raise MediaUrlExpiredError("403")
        served = ByteRange(0, min(byte_range.end, len(data) - 1))
        return MediaStream(served, len(data), [data[: served.end + 1]])

    gateway = YtDlpGateway(recorder=recorder, media=media)
    fmt = make_format("137")
    assert gateway.probe_dash_ranges(fmt) == mp4_ranges()
    with gateway.open_media(fmt, ByteRange(0, 9)) as stream:
        assert stream.read() == data[:10]
    with pytest.raises(MediaUrlExpiredError):
        gateway.open_media(fmt, ByteRange(10, 19))

    # Successful reads aren't recorded (a video is hundreds of them); probes are.
    assert [(e.operation, e.success, e.error_kind) for e in recorder.events] == [
        ("probe_dash_ranges", True, None),
        ("open_media", False, "media_url_expired"),
    ]


# FakeGateway


def test_fake_gateway_serves_ranges_and_probes() -> None:
    gateway = FakeGateway()
    fmt = make_format("251", mime_type="audio/webm", codecs="opus")
    gateway.add_video(make_video("aaaaaaaaaaa"), [fmt])
    gateway.add_media(fmt.url, webm())

    assert gateway.probe_dash_ranges(fmt) == webm_ranges()
    with gateway.open_media(fmt, ByteRange(len(webm()) - 4, len(webm()) + 100)) as stream:
        assert stream.read() == webm()[-4:]
        assert stream.byte_range.end == len(webm()) - 1
    with pytest.raises(RangeNotSatisfiableError):
        gateway.open_media(fmt, ByteRange(len(webm()), len(webm())))

    gateway.fail("open_media", fmt.url, MediaUrlExpiredError("403"))
    with pytest.raises(MediaUrlExpiredError):
        gateway.open_media(fmt, ByteRange(0, 1))
