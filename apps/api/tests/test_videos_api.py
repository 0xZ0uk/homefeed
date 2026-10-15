import sqlite3
import struct
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from homefeed_api.main import app, get_gateway, get_playback
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway import ByteRange, ExtractionError, MediaUrlExpiredError, Video
from homefeed_core.gateway.events import ExtractorEvent, SqlEventRecorder
from homefeed_core.gateway.fake import FakeGateway, make_channel, make_format, make_video
from homefeed_core.playback import Playback
from homefeed_core.tags import ProposedTag, set_llm_tags
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
    assert body["tags"] == []
    assert body["channel_thumbnail_url"] is None  # the channel was never looked up
    assert body["is_stale"] is False
    with get_session_factory()() as session:
        stored = get_stored_video(session, VIDEO)
    assert stored is not None and stored.title == "Planing"


def test_get_video_has_the_channels_picture_once_it_is_known(
    client: TestClient, gateway: FakeGateway
) -> None:
    client.get(f"/videos/{VIDEO}")
    with get_session_factory().begin() as session:
        session.execute(
            text("UPDATE channels SET thumbnail_url = 'https://example.invalid/wood.jpg'")
        )

    assert client.get(f"/videos/{VIDEO}").json()["channel_thumbnail_url"] == (
        "https://example.invalid/wood.jpg"
    )

    # The stored copy has it too.
    fresh = Playback(gateway)
    app.dependency_overrides[get_playback] = lambda: fresh
    gateway.fail("get_video", VIDEO, ExtractionError("network down"))
    body = client.get(f"/videos/{VIDEO}").json()
    assert body["is_stale"] is True
    assert body["channel_thumbnail_url"] == "https://example.invalid/wood.jpg"


def test_get_video_returns_its_tags(client: TestClient, gateway: FakeGateway) -> None:
    client.get(f"/videos/{VIDEO}")
    with get_session_factory().begin() as session:
        proposals = [ProposedTag("hand tools", 0.6), ProposedTag("Woodworking", 0.9)]
        set_llm_tags(session, VIDEO, proposals, prompt_version=2)
    expected = [
        {"slug": "woodworking", "label": "Woodworking", "source": "llm", "confidence": 0.9},
        {"slug": "hand-tools", "label": "hand tools", "source": "llm", "confidence": 0.6},
    ]

    assert client.get(f"/videos/{VIDEO}").json()["tags"] == expected

    # The stored copy has them too.
    fresh = Playback(gateway)
    app.dependency_overrides[get_playback] = lambda: fresh
    gateway.fail("get_video", VIDEO, ExtractionError("network down"))
    body = client.get(f"/videos/{VIDEO}").json()
    assert body["is_stale"] is True
    assert body["tags"] == expected


def commit_during_fetches(gateway: FakeGateway) -> None:
    """Make each `get_video` commit to the database on its own connection, as the real
    Gateway does when it records its extractor event (and the worker may do any time)."""
    fetch = gateway.get_video
    recorder = SqlEventRecorder(get_session_factory())

    def get_video(video_id: str) -> Video:
        recorder.record(ExtractorEvent("get_video", video_id, True, datetime.now(UTC)))
        return fetch(video_id)

    gateway.get_video = get_video  # type: ignore[method-assign]


def test_get_video_survives_a_commit_during_the_fetch(
    client: TestClient, gateway: FakeGateway
) -> None:
    # A first view used to fail with "database is locked" (a bare 500): the request read
    # in a transaction held open across the fetch, so its write lost to that commit.
    commit_during_fetches(gateway)

    response = client.get(f"/videos/{VIDEO}")

    assert response.status_code == 200, response.text
    assert response.json()["is_stale"] is False
    with get_session_factory().begin() as session:
        assert get_stored_video(session, VIDEO) is not None


def test_a_locked_database_is_a_503(client: TestClient, gateway: FakeGateway) -> None:
    def locked(video_id: str) -> Video:
        raise OperationalError("INSERT ...", {}, sqlite3.OperationalError("database is locked"))

    gateway.get_video = locked  # type: ignore[method-assign]

    response = client.get(f"/videos/{VIDEO}")

    assert (response.status_code, response.json()) == (
        503,
        {"detail": "The database is busy; try again in a moment"},
    )


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


def test_add_and_remove_tags_by_hand(client: TestClient) -> None:
    client.get(f"/videos/{VIDEO}")
    with get_session_factory().begin() as session:
        set_llm_tags(
            session,
            VIDEO,
            [ProposedTag("woodworking", 0.9), ProposedTag("hand tools", 0.6)],
            prompt_version=2,
        )

    added = client.post(f"/videos/{VIDEO}/tags", json={"label": "  Dovetail Joints "})
    assert added.status_code == 200
    assert added.json() == [
        {
            "slug": "dovetail-joints",
            "label": "Dovetail Joints",
            "source": "manual",
            "confidence": 1,
        },
        {"slug": "woodworking", "label": "woodworking", "source": "llm", "confidence": 0.9},
        {"slug": "hand-tools", "label": "hand tools", "source": "llm", "confidence": 0.6},
    ]

    removed = client.delete(f"/videos/{VIDEO}/tags/hand-tools")
    assert removed.status_code == 200
    assert [tag["slug"] for tag in removed.json()] == ["dovetail-joints", "woodworking"]
    # Removing it again, or a tag the video never had, changes nothing.
    assert client.delete(f"/videos/{VIDEO}/tags/hand-tools").json() == removed.json()
    assert client.delete(f"/videos/{VIDEO}/tags/nope").json() == removed.json()

    # Retagging neither drops the manual tag nor brings back the removed one.
    with get_session_factory().begin() as session:
        proposals = [ProposedTag("hand tools", 0.9), ProposedTag("dovetail joints", 0.5)]
        set_llm_tags(session, VIDEO, proposals, prompt_version=3)
    tags = client.get(f"/videos/{VIDEO}").json()["tags"]
    assert [(tag["slug"], tag["source"]) for tag in tags] == [("dovetail-joints", "manual")]

    # Adding a removed tag brings it back.
    again = client.post(f"/videos/{VIDEO}/tags", json={"label": "hand tools"})
    assert "hand-tools" in [tag["slug"] for tag in again.json()]


def test_tag_edits_reject_unknown_videos_and_unusable_text(client: TestClient) -> None:
    assert client.post("/videos/zzzzzzzzzzz/tags", json={"label": "rust"}).status_code == 404
    assert client.delete("/videos/zzzzzzzzzzz/tags/rust").status_code == 404
    client.get(f"/videos/{VIDEO}")

    for label in ["", "  ", "***", "x" * 60]:
        response = client.post(f"/videos/{VIDEO}/tags", json={"label": label})
        assert response.status_code == 422, label
    assert client.post(f"/videos/{VIDEO}/tags", json={}).status_code == 422
    assert client.get(f"/videos/{VIDEO}").json()["tags"] == []


def test_suggest_tags(client: TestClient) -> None:
    client.get(f"/videos/{VIDEO}")
    for label in ["rust", "rustacean", "woodworking"]:
        client.post(f"/videos/{VIDEO}/tags", json={"label": label})
    client.delete(f"/videos/{VIDEO}/tags/rustacean")

    body = client.get("/tags/suggest", params={"q": "Rus"}).json()
    assert body == [
        {"slug": "rust", "label": "rust", "video_count": 1},
        {"slug": "rustacean", "label": "rustacean", "video_count": 0},
    ]
    assert [t["slug"] for t in client.get("/tags/suggest", params={"limit": 1}).json()] == ["rust"]
    assert client.get("/tags/suggest", params={"q": "zzz"}).json() == []
    assert client.get("/tags/suggest", params={"limit": 0}).status_code == 422
