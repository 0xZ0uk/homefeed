from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app, get_gateway
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway import ExtractionError, GatewayError, RateLimitedError
from homefeed_core.gateway.fake import FakeGateway, make_channel

WOOD = make_channel(
    "UC" + "w" * 22,
    title="Woodworking",
    handle="@wood",
    thumbnail_url="https://example.invalid/wood.jpg",
)
BIRDS = make_channel("UC" + "b" * 22, title="Birds", handle="@birds")


@pytest.fixture
def gateway() -> FakeGateway:
    gateway = FakeGateway()
    gateway.add_channel(WOOD)
    gateway.add_channel(BIRDS)
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


def subscribe(client: TestClient, url: str = "https://www.youtube.com/@wood") -> dict:
    response = client.post("/channels", json={"url": url})
    assert response.status_code == 201, response.text
    return response.json()


def stored(sql: str) -> list[tuple]:
    with get_session_factory()() as session:
        return [tuple(row) for row in session.execute(text(sql))]


def test_subscribe_by_url(client: TestClient, gateway: FakeGateway) -> None:
    body = subscribe(client)

    assert body == {
        "channel_id": WOOD.id,
        "title": "Woodworking",
        "handle": "@wood",
        "url": WOOD.url,
        "thumbnail_url": "https://example.invalid/wood.jpg",
        "prior": "neutral",
        "pinned": False,
        "muted": False,
        "subscribed_at": body["subscribed_at"],
        "updated_at": body["updated_at"],
    }
    assert gateway.calls == [("resolve_url", "https://www.youtube.com/@wood")]
    assert stored("SELECT id, title, handle FROM channels") == [(WOOD.id, "Woodworking", "@wood")]
    assert stored("SELECT channel_id, prior, pinned, muted FROM channel_prefs") == [
        (WOOD.id, "neutral", 0, 0)
    ]


def test_subscribe_again_returns_200_and_keeps_prefs(client: TestClient) -> None:
    subscribe(client)
    client.patch(f"/channels/{WOOD.id}", json={"prior": "love"})

    response = client.post("/channels", json={"url": f"https://www.youtube.com/channel/{WOOD.id}"})

    assert response.status_code == 200
    assert response.json()["prior"] == "love"
    assert len(stored("SELECT * FROM channel_prefs")) == 1


@pytest.mark.parametrize(
    "url",
    [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://example.com/@wood",
        "not a url at all",
    ],
)
def test_subscribe_rejects_non_channel_urls(client: TestClient, url: str) -> None:
    response = client.post("/channels", json={"url": url})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert stored("SELECT * FROM channels") == []


@pytest.mark.parametrize("body", [{}, {"url": ""}])
def test_subscribe_validates_body(client: TestClient, body: dict) -> None:
    assert client.post("/channels", json=body).status_code == 422


def test_subscribe_unknown_channel_is_404(client: TestClient) -> None:
    response = client.post("/channels", json={"url": "https://www.youtube.com/@nobody"})
    assert response.status_code == 404


@pytest.mark.parametrize("error", [ExtractionError("boom"), RateLimitedError("slow down")])
def test_subscribe_gateway_failure_is_502(
    client: TestClient, gateway: FakeGateway, error: GatewayError
) -> None:
    url = "https://www.youtube.com/@wood"
    gateway.fail("resolve_url", url, error)

    assert client.post("/channels", json={"url": url}).status_code == 502
    assert stored("SELECT * FROM channels") == []


def test_list_channels(client: TestClient) -> None:
    assert client.get("/channels").json() == []
    subscribe(client)
    subscribe(client, "@birds")

    response = client.get("/channels")

    assert response.status_code == 200
    assert [c["title"] for c in response.json()] == ["Birds", "Woodworking"]


def test_update_prior_pin_and_mute(client: TestClient) -> None:
    subscribe(client)

    response = client.patch(
        f"/channels/{WOOD.id}", json={"prior": "skeptical", "pinned": True, "muted": True}
    )

    assert response.status_code == 200
    body = response.json()
    assert (body["prior"], body["pinned"], body["muted"]) == ("skeptical", True, True)
    assert stored("SELECT prior, pinned, muted FROM channel_prefs") == [("skeptical", 1, 1)]


def test_update_leaves_omitted_fields(client: TestClient) -> None:
    subscribe(client)
    client.patch(f"/channels/{WOOD.id}", json={"prior": "like", "pinned": True})

    body = client.patch(f"/channels/{WOOD.id}", json={"pinned": False}).json()

    assert (body["prior"], body["pinned"], body["muted"]) == ("like", False, False)


@pytest.mark.parametrize("body", [{"prior": "hate"}, {"pinned": "maybe"}])
def test_update_rejects_invalid_values(client: TestClient, body: dict) -> None:
    subscribe(client)
    assert client.patch(f"/channels/{WOOD.id}", json=body).status_code == 422


def test_update_unsubscribed_channel_is_404(client: TestClient) -> None:
    assert client.patch(f"/channels/{WOOD.id}", json={"pinned": True}).status_code == 404


@pytest.mark.parametrize("channel_id", ["UCshort", "XX" + "w" * 22, "UC" + "w" * 21 + "!"])
def test_rejects_invalid_channel_ids(client: TestClient, channel_id: str) -> None:
    assert client.patch(f"/channels/{channel_id}", json={}).status_code == 422
    assert client.delete(f"/channels/{channel_id}").status_code == 422


def test_unsubscribe(client: TestClient) -> None:
    subscribe(client)

    response = client.delete(f"/channels/{WOOD.id}")

    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/channels").json() == []
    assert stored("SELECT id FROM channels") == [(WOOD.id,)]
    assert client.delete(f"/channels/{WOOD.id}").status_code == 404


def test_openapi_lists_priors_as_enum(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()["components"]["schemas"]
    assert schema["SubscribedChannel"]["properties"]["prior"]["enum"] == [
        "love",
        "like",
        "neutral",
        "skeptical",
    ]
