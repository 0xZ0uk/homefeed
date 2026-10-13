"""`GET /videos/{id}/segments` (SponsorBlock)."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from homefeed_api.main import app, get_gateway, get_playback
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway.fake import FakeGateway, make_video
from homefeed_core.playback import Playback
from homefeed_core.sponsorblock import SponsorBlockError, SponsorSegment

VIDEO = "aaaaaaaaaaa"


class FakeSponsorBlock:
    def __init__(self) -> None:
        self.segments: dict[str, list[SponsorSegment]] = {}
        self.error: SponsorBlockError | None = None
        self.calls: list[str] = []

    def skip_segments(self, video_id: str) -> list[SponsorSegment]:
        self.calls.append(video_id)
        if self.error is not None:
            raise self.error
        return self.segments.get(video_id, [])


@pytest.fixture
def gateway() -> FakeGateway:
    gateway = FakeGateway()
    gateway.add_video(make_video(VIDEO))
    gateway.add_video(make_video("bbbbbbbbbbb"))
    return gateway


@pytest.fixture
def sponsorblock() -> FakeSponsorBlock:
    return FakeSponsorBlock()


@pytest.fixture
def client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    gateway: FakeGateway,
    sponsorblock: FakeSponsorBlock,
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    playback = Playback(gateway, sponsorblock=sponsorblock)
    app.dependency_overrides[get_gateway] = lambda: gateway
    app.dependency_overrides[get_playback] = lambda: playback
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


# Segments


def test_segments(client: TestClient, sponsorblock: FakeSponsorBlock) -> None:
    sponsorblock.segments[VIDEO] = [
        SponsorSegment("uuid-1", "sponsor", 12.5, 40.0),
        SponsorSegment("uuid-2", "selfpromo", 300.0, 310.0),
    ]

    response = client.get(f"/videos/{VIDEO}/segments")

    assert response.status_code == 200
    assert response.json() == [
        {"id": "uuid-1", "category": "sponsor", "start_seconds": 12.5, "end_seconds": 40.0},
        {"id": "uuid-2", "category": "selfpromo", "start_seconds": 300.0, "end_seconds": 310.0},
    ]
    client.get(f"/videos/{VIDEO}/segments")
    assert sponsorblock.calls == [VIDEO]  # cached


def test_segments_none(client: TestClient) -> None:
    response = client.get("/videos/bbbbbbbbbbb/segments")
    assert response.status_code == 200
    assert response.json() == []


def test_segments_errors(client: TestClient, sponsorblock: FakeSponsorBlock) -> None:
    sponsorblock.error = SponsorBlockError("Could not reach SponsorBlock")
    response = client.get(f"/videos/{VIDEO}/segments")
    assert response.status_code == 502
    assert "SponsorBlock" in response.json()["detail"]
    assert client.get("/videos/not-an-id/segments").status_code == 422
