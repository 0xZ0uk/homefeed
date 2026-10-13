from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from homefeed_api.main import app, get_gateway
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway import (
    ExtractionError,
    FeaturedChannel,
    UnavailableError,
    UploadSummary,
)
from homefeed_core.gateway.events import ExtractorEvent, SqlEventRecorder
from homefeed_core.gateway.fake import FakeGateway, make_channel, make_video

WOOD = make_channel("UC" + "w" * 22, title="Woodworking", handle="@wood")
BIRDS = make_channel("UC" + "b" * 22, title="Birds", handle="@birds")
CARPENTRY = make_channel(
    "UC" + "c" * 22,
    title="Carpentry",
    handle="@carpentry",
    thumbnail_url="https://example.invalid/carpentry.jpg",
)
TOOLS = make_channel("UC" + "t" * 22, title="Tools")


@pytest.fixture
def gateway() -> FakeGateway:
    gateway = FakeGateway()
    gateway.add_channel(WOOD)
    gateway.add_channel(BIRDS)
    gateway.add_channel(
        CARPENTRY,
        [
            make_video(
                "aaaaaaaaaaa",
                channel=CARPENTRY,
                title="Dovetails",
                duration_seconds=900,
                view_count=1200,
            ),
            make_video("bbbbbbbbbbb", channel=CARPENTRY, title="Mortises"),
        ],
    )
    gateway.add_featured(WOOD.id, [CARPENTRY, TOOLS, BIRDS], subscriber_count=5000)
    return gateway


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gateway: FakeGateway
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    app.dependency_overrides[get_gateway] = lambda: gateway
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def subscribe(client: TestClient, handle: str, prior: str = "neutral") -> None:
    response = client.post("/channels", json={"url": f"https://www.youtube.com/{handle}"})
    assert response.status_code == 201, response.text
    channel_id = response.json()["channel_id"]
    assert client.patch(f"/channels/{channel_id}", json={"prior": prior}).status_code == 200


def test_featured_channels(client: TestClient, gateway: FakeGateway) -> None:
    subscribe(client, "@birds")

    response = client.get(f"/channels/{WOOD.id}/featured")

    assert response.status_code == 200
    body = response.json()
    assert [(c["channel_id"], c["subscribed"]) for c in body] == [
        (CARPENTRY.id, False),
        (TOOLS.id, False),
        (BIRDS.id, True),
    ]
    assert body[0] == {
        "channel_id": CARPENTRY.id,
        "title": "Carpentry",
        "handle": "@carpentry",
        "url": CARPENTRY.url,
        "thumbnail_url": "https://example.invalid/carpentry.jpg",
        "subscriber_count": 5000,
        "subscribed": False,
    }


def test_featured_channels_are_cached_for_known_channels(
    client: TestClient, gateway: FakeGateway
) -> None:
    subscribe(client, "@wood")

    first = client.get(f"/channels/{WOOD.id}/featured").json()
    gateway.fail("get_featured_channels", WOOD.id, ExtractionError("blocked"))
    second = client.get(f"/channels/{WOOD.id}/featured").json()

    assert first == second
    assert gateway.calls.count(("get_featured_channels", WOOD.id)) == 1


def test_featured_channels_survive_a_commit_during_the_fetch(
    client: TestClient, gateway: FakeGateway
) -> None:
    subscribe(client, "@wood")  # known, so the fetched channels are stored
    # Like the real Gateway, record an extractor event (a commit) while fetching.
    fetch = gateway.get_featured_channels
    recorder = SqlEventRecorder(get_session_factory())

    def get_featured_channels(channel_id: str) -> list[FeaturedChannel]:
        event = ExtractorEvent("get_featured_channels", channel_id, True, datetime.now(UTC))
        recorder.record(event)
        return fetch(channel_id)

    gateway.get_featured_channels = get_featured_channels  # type: ignore[method-assign]

    response = client.get(f"/channels/{WOOD.id}/featured")

    assert response.status_code == 200, response.text
    assert [c["channel_id"] for c in response.json()] == [CARPENTRY.id, TOOLS.id, BIRDS.id]


def test_featured_channels_errors(client: TestClient, gateway: FakeGateway) -> None:
    gateway.fail("get_featured_channels", BIRDS.id, ExtractionError("blocked"))

    missing = client.get("/channels/UC" + "z" * 22 + "/featured")
    broken = client.get(f"/channels/{BIRDS.id}/featured")
    bad = client.get("/channels/not-a-channel/featured")

    assert missing.status_code == 404
    assert (broken.status_code, broken.json()) == (502, {"detail": "blocked"})
    assert bad.status_code == 422


def test_channel_uploads(client: TestClient, gateway: FakeGateway) -> None:
    response = client.get(f"/channels/{CARPENTRY.id}/uploads", params={"limit": 1})

    assert response.status_code == 200
    assert response.json() == {
        "channel": {
            "channel_id": CARPENTRY.id,
            "title": "Carpentry",
            "handle": "@carpentry",
            "url": CARPENTRY.url,
            "thumbnail_url": "https://example.invalid/carpentry.jpg",
            "subscribed": False,
        },
        "videos": [
            {
                "id": "aaaaaaaaaaa",
                "title": "Dovetails",
                "duration_seconds": 900,
                "view_count": 1200,
                "thumbnail_url": None,
                "published_at": None,
                "live_status": "not_live",
            }
        ],
    }


def test_channel_uploads_errors(client: TestClient, gateway: FakeGateway) -> None:
    gateway.fail("get_channel_uploads", WOOD.id, UnavailableError("This channel does not exist"))

    assert client.get(f"/channels/{WOOD.id}/uploads").status_code == 404
    assert client.get(f"/channels/{CARPENTRY.id}/uploads?limit=0").status_code == 422


def test_suggested_channels(client: TestClient, gateway: FakeGateway) -> None:
    assert client.get("/discover/suggested-channels").json() == []
    subscribe(client, "@wood", "love")
    subscribe(client, "@birds")

    response = client.get("/discover/suggested-channels")

    assert response.status_code == 200
    body = response.json()
    # Birds is featured too, but already subscribed.
    assert [c["channel_id"] for c in body] == [CARPENTRY.id, TOOLS.id]
    assert body[0] == {
        "channel_id": CARPENTRY.id,
        "title": "Carpentry",
        "handle": "@carpentry",
        "url": CARPENTRY.url,
        "thumbnail_url": "https://example.invalid/carpentry.jpg",
        "subscriber_count": 5000,
        "featured_by": [{"channel_id": WOOD.id, "title": "Woodworking"}],
    }
    # Fetched once, then served from storage.
    client.get("/discover/suggested-channels", params={"limit": 1})
    assert gateway.calls.count(("get_featured_channels", WOOD.id)) == 1
    assert len(client.get("/discover/suggested-channels", params={"limit": 1}).json()) == 1


def test_suggestions_tolerate_gateway_failures(client: TestClient, gateway: FakeGateway) -> None:
    subscribe(client, "@wood", "like")
    gateway.fail("get_featured_channels", WOOD.id, ExtractionError("blocked"))

    response = client.get("/discover/suggested-channels")

    assert (response.status_code, response.json()) == (200, [])


def test_upload_times_are_iso(client: TestClient, gateway: FakeGateway) -> None:
    gateway.uploads[CARPENTRY.id][0] = UploadSummary(
        id="aaaaaaaaaaa", title="Dovetails", published_at=datetime(2026, 10, 1, tzinfo=UTC)
    )

    [video, _] = client.get(f"/channels/{CARPENTRY.id}/uploads").json()["videos"]

    assert video["published_at"] == "2026-10-01T00:00:00.000Z"
