import struct
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from homefeed_api.main import app, get_gateway, get_playback
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway import ByteRange, ExtractionError, MediaUrlExpiredError
from homefeed_core.gateway.fake import FakeGateway, make_channel, make_format, make_video
from homefeed_core.playback import Playback
from homefeed_core.videos import get_stored_video

VIDEO = "aaaaaaaaaaa"
NS = {"d": "urn:mpeg:dash:schema:mpd:2011"}
CHANNEL = make_channel("UC" + "w" * 22, title="Woodworking", handle="@wood")


def box(kind: bytes, payload: int) -> bytes:
    return struct.pack(">I4s", 8 + payload, kind) + bytes(payload)


# ftyp(24) moov(108) sidx(208) moof mdat: init 0-131, index 132-339
MEDIA = box(b"ftyp", 16) + box(b"moov", 100) + box(b"sidx", 200) + box(b"mdat", 50_000)


@pytest.fixture
def gateway() -> FakeGateway:
    gateway = FakeGateway()
    formats = [
        make_format(
            "137",
            kind="video",
            url="https://googlevideo.invalid/137?lmt=1",
            mime_type="video/mp4",
            codecs="avc1.640028",
            width=1920,
            height=1080,
            filesize=len(MEDIA),
            init_range=ByteRange(0, 131),
            index_range=ByteRange(132, 339),
        ),
        # No ranges: the manifest probes the file for them.
        make_format("140", url="https://googlevideo.invalid/140?lmt=1", filesize=len(MEDIA)),
    ]
    video = make_video(VIDEO, channel=CHANNEL, title="Planing", description="How to plane")
    gateway.add_video(video, formats)
    for fmt in formats:
        gateway.add_media(fmt.url, MEDIA)
    return gateway


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gateway: FakeGateway
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    playback = Playback(gateway, chunk_bytes=16 * 1024)
    app.dependency_overrides[get_gateway] = lambda: gateway
    app.dependency_overrides[get_playback] = lambda: playback
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def test_get_video_returns_and_stores_metadata(client: TestClient) -> None:
    response = client.get(f"/videos/{VIDEO}")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Planing"
    assert body["description"] == "How to plane"
    assert (body["channel_id"], body["channel_title"], body["channel_handle"]) == (
        CHANNEL.id,
        "Woodworking",
        "@wood",
    )
    assert body["duration_seconds"] == 600
    assert body["published_at"] == "2026-01-01T00:00:00.000Z"
    assert body["is_stale"] is False
    with get_session_factory()() as session:
        stored = get_stored_video(session, VIDEO)
    assert stored is not None and stored.title == "Planing"


def test_get_video_falls_back_to_the_stored_copy(client: TestClient, gateway: FakeGateway) -> None:
    client.get(f"/videos/{VIDEO}")
    fresh = Playback(gateway)
    app.dependency_overrides[get_playback] = lambda: fresh
    gateway.fail("get_video", VIDEO, ExtractionError("network down"))

    response = client.get(f"/videos/{VIDEO}")

    assert response.status_code == 200
    assert response.json()["title"] == "Planing"
    assert response.json()["is_stale"] is True


def test_get_video_errors(client: TestClient, gateway: FakeGateway) -> None:
    assert client.get("/videos/bbbbbbbbbbb").status_code == 404
    gateway.fail("get_video", "ccccccccccc", ExtractionError("network down"))
    assert client.get("/videos/ccccccccccc").status_code == 502
    assert client.get("/videos/not-an-id").status_code == 422


def test_manifest_is_a_dash_mpd_with_proxy_urls(client: TestClient) -> None:
    response = client.get(f"/videos/{VIDEO}/manifest.mpd")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/dash+xml"
    assert "googlevideo" not in response.text
    root = ET.fromstring(response.text)
    reps = {r.attrib["id"]: r for r in root.iterfind(".//d:Representation", NS)}
    assert set(reps) == {"137", "140"}
    for rep in reps.values():
        assert rep.findtext("d:BaseURL", namespaces=NS) == f"media/{rep.attrib['id']}"
        segment_base = rep.find("d:SegmentBase", NS)
        assert segment_base is not None and segment_base.attrib["indexRange"] == "132-339"


def test_manifest_errors(client: TestClient, gateway: FakeGateway) -> None:
    assert client.get("/videos/bbbbbbbbbbb/manifest.mpd").status_code == 404
    gateway.add_video(make_video("ddddddddddd"), [make_format("233", protocol="m3u8_native")])
    response = client.get("/videos/ddddddddddd/manifest.mpd")
    assert response.status_code == 422
    assert "No playable streams" in response.json()["detail"]


def test_media_serves_ranges(client: TestClient) -> None:
    response = client.get(f"/videos/{VIDEO}/media/137", headers={"Range": "bytes=100-199"})

    assert response.status_code == 206
    assert response.headers["content-range"] == f"bytes 100-199/{len(MEDIA)}"
    assert response.headers["content-length"] == "100"
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-type"] == "video/mp4"
    assert response.content == MEDIA[100:200]


def test_media_streams_long_ranges_in_upstream_chunks(
    client: TestClient, gateway: FakeGateway
) -> None:
    response = client.get(f"/videos/{VIDEO}/media/137", headers={"Range": "bytes=0-"})

    assert response.status_code == 206
    assert response.content == MEDIA
    assert len(gateway.media_reads) == 4  # 50 KB in 16 KB upstream reads
    assert all(r.end - r.start < 16 * 1024 for _, r in gateway.media_reads)


def test_media_without_range_is_the_whole_file(client: TestClient) -> None:
    response = client.get(f"/videos/{VIDEO}/media/140")
    assert response.status_code == 200
    assert "content-range" not in response.headers
    assert response.content == MEDIA


def test_media_errors(client: TestClient) -> None:
    past_end = client.get(f"/videos/{VIDEO}/media/137", headers={"Range": f"bytes={len(MEDIA)}-"})
    assert past_end.status_code == 416
    assert past_end.headers["content-range"] == f"bytes */{len(MEDIA)}"
    assert client.get(f"/videos/{VIDEO}/media/999").status_code == 404
    assert client.get("/videos/bbbbbbbbbbb/media/137").status_code == 404
    assert client.get(f"/videos/{VIDEO}/media/bad%20id").status_code == 422


def test_media_refreshes_expired_urls(client: TestClient, gateway: FakeGateway) -> None:
    client.get(f"/videos/{VIDEO}/media/137", headers={"Range": "bytes=0-9"})
    old = gateway.formats[VIDEO][0]
    new = replace(old, url="https://googlevideo.invalid/137?lmt=1&n=2")
    gateway.formats[VIDEO] = [new]
    gateway.add_media(new.url, MEDIA)
    gateway.fail("open_media", old.url, MediaUrlExpiredError("403"))

    response = client.get(f"/videos/{VIDEO}/media/137", headers={"Range": "bytes=10-19"})

    assert response.status_code == 206
    assert response.content == MEDIA[10:20]


def test_media_of_a_replaced_file_is_a_conflict(client: TestClient, gateway: FakeGateway) -> None:
    client.get(f"/videos/{VIDEO}/media/137", headers={"Range": "bytes=0-9"})
    old = gateway.formats[VIDEO][0]
    gateway.formats[VIDEO] = [replace(old, url="https://googlevideo.invalid/137?lmt=2")]
    gateway.fail("open_media", old.url, MediaUrlExpiredError("403"))

    assert client.get(f"/videos/{VIDEO}/media/137", headers={"Range": "bytes=0-9"}).status_code == (
        409
    )
