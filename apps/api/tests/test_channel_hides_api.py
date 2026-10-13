from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from homefeed_api.main import app, get_gateway
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.feeds import load_curation
from homefeed_core.gateway import UnavailableError
from homefeed_core.gateway.fake import FakeGateway, make_channel, make_video

WOOD = make_channel("UC" + "w" * 22, title="Woodworking", handle="@wood")
CARPENTRY = make_channel(
    "UC" + "c" * 22,
    title="Carpentry",
    handle="@carpentry",
    thumbnail_url="https://example.invalid/carpentry.jpg",
    banner_url="https://example.invalid/carpentry-banner.jpg",
    description="Joinery videos",
    subscriber_count=4200,
)
TOOLS = make_channel("UC" + "t" * 22, title="Tools")
BIRDS = make_channel("UC" + "b" * 22, title="Birds", handle="@birds")


@pytest.fixture
def gateway() -> FakeGateway:
    gateway = FakeGateway()
    gateway.add_channel(WOOD)
    gateway.add_channel(
        CARPENTRY, [make_video("aaaaaaaaaaa", channel=CARPENTRY, title="Dovetails")]
    )
    gateway.add_channel(TOOLS)
    gateway.add_channel(BIRDS)
    gateway.add_featured(WOOD.id, [CARPENTRY, TOOLS, BIRDS])
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


def suggested_ids(client: TestClient, **params: Any) -> list[str]:
    response = client.get("/discover/suggested-channels", params=params)
    assert response.status_code == 200, response.text
    return [c["channel_id"] for c in response.json()]


def test_hide_list_and_unhide(client: TestClient) -> None:
    subscribe(client, "@wood", "love")
    assert suggested_ids(client) == [CARPENTRY.id, TOOLS.id, BIRDS.id]

    dismissed = client.put(f"/channels/{TOOLS.id}/hide", json={"kind": "dismissed"})
    blocked = client.put(f"/channels/{CARPENTRY.id}/hide", json={"kind": "blocked"})

    assert dismissed.status_code == 200
    assert dismissed.json()["kind"] == "dismissed"
    assert blocked.json() == {
        "channel_id": CARPENTRY.id,
        "title": "Carpentry",
        "handle": "@carpentry",
        "thumbnail_url": "https://example.invalid/carpentry.jpg",
        "kind": "blocked",
        "hidden_at": blocked.json()["hidden_at"],
    }
    assert [h["channel_id"] for h in client.get("/channel-hides").json()] == [
        CARPENTRY.id,
        TOOLS.id,
    ]
    assert suggested_ids(client) == [BIRDS.id]

    assert client.delete(f"/channels/{TOOLS.id}/hide").status_code == 204
    assert client.delete(f"/channels/{TOOLS.id}/hide").status_code == 404
    assert suggested_ids(client) == [TOOLS.id, BIRDS.id]


def test_hide_validation(client: TestClient) -> None:
    unknown = client.put("/channels/UC" + "z" * 22 + "/hide", json={"kind": "dismissed"})
    bad_kind = client.put(f"/channels/{WOOD.id}/hide", json={"kind": "nope"})

    assert unknown.status_code == 404
    assert bad_kind.status_code == 422


def test_blocked_channel_is_muted_in_the_feed_and_subscribing_clears_it(
    client: TestClient,
) -> None:
    subscribe(client, "@wood", "love")
    client.get("/discover/suggested-channels")
    client.put(f"/channels/{CARPENTRY.id}/hide", json={"kind": "blocked"})

    with get_session_factory()() as session:
        assert load_curation(session)[CARPENTRY.id].muted

    subscribe(client, "@carpentry")
    assert client.get("/channel-hides").json() == []
    with get_session_factory()() as session:
        assert not load_curation(session)[CARPENTRY.id].muted


def test_suggestions_rotate_with_exclude(client: TestClient) -> None:
    subscribe(client, "@wood", "love")

    assert suggested_ids(client, limit=2) == [CARPENTRY.id, TOOLS.id]
    assert suggested_ids(client, limit=2, exclude=[CARPENTRY.id, TOOLS.id]) == [
        BIRDS.id,
        CARPENTRY.id,
    ]
    # Everything excluded: wraps to the top rather than returning nothing.
    assert suggested_ids(client, exclude=[CARPENTRY.id, TOOLS.id, BIRDS.id]) == [
        CARPENTRY.id,
        TOOLS.id,
        BIRDS.id,
    ]


def test_refresh_refetches_ignoring_the_cache(client: TestClient, gateway: FakeGateway) -> None:
    subscribe(client, "@wood", "love")
    suggested_ids(client)
    suggested_ids(client)
    assert gateway.calls.count(("get_featured_channels", WOOD.id)) == 1
    gateway.add_featured(WOOD.id, [TOOLS, BIRDS, CARPENTRY])

    response = client.post(
        "/discover/suggested-channels/refresh", params={"exclude": [TOOLS.id], "limit": 2}
    )

    assert response.status_code == 200, response.text
    assert gateway.calls.count(("get_featured_channels", WOOD.id)) == 2
    # The new order applies, with the shown channel moved after the unseen ones.
    assert [c["channel_id"] for c in response.json()] == [BIRDS.id, CARPENTRY.id]


def test_channel_profile(client: TestClient) -> None:
    response = client.get(f"/channels/{CARPENTRY.id}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["banner_url"] == "https://example.invalid/carpentry-banner.jpg"
    assert body["description"] == "Joinery videos"
    assert body["subscriber_count"] == 4200
    assert (body["subscribed"], body["hidden"]) == (False, None)
    assert [v["id"] for v in body["videos"]] == ["aaaaaaaaaaa"]

    # Fetching stored the channel, so it can be hidden, and the profile shows it.
    assert (
        client.put(f"/channels/{CARPENTRY.id}/hide", json={"kind": "dismissed"}).status_code == 200
    )
    assert client.get(f"/channels/{CARPENTRY.id}").json()["hidden"] == "dismissed"
    subscribe(client, "@carpentry")
    after = client.get(f"/channels/{CARPENTRY.id}").json()
    assert (after["subscribed"], after["hidden"]) == (True, None)


def test_channel_profile_errors(client: TestClient, gateway: FakeGateway) -> None:
    gateway.fail("get_channel_uploads", WOOD.id, UnavailableError("gone"))

    assert client.get(f"/channels/{WOOD.id}").status_code == 404
    assert client.get(f"/channels/{CARPENTRY.id}?limit=51").status_code == 422
