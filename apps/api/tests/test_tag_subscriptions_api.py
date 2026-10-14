from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.tags import resolve_tag


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    with TestClient(app) as client:
        yield client
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def make_tag(label: str = "Rust") -> int:
    with get_session_factory().begin() as session:
        tag = resolve_tag(session, label)
        assert tag is not None
        return tag.id


def test_subscribe_lists_the_tag_and_shows_on_the_tag_page(client: TestClient) -> None:
    tag_id = make_tag()
    assert client.get("/tags/rust").json()["subscription"] is None
    assert client.get("/tag-subscriptions").json() == []

    response = client.post("/tags/rust/subscribe")

    assert response.status_code == 200
    subscription = response.json()
    assert subscription == {
        "tag_id": tag_id,
        "slug": "rust",
        "label": "Rust",
        "weight": 0.5,
        "hide": False,
        "created_at": subscription["created_at"],
        "updated_at": subscription["updated_at"],
    }
    assert client.post("/tags/rust/subscribe").json() == subscription  # idempotent
    assert client.get("/tags/rust").json()["subscription"] == subscription
    assert client.get("/tag-subscriptions").json() == [subscription]

    updated = client.patch("/tags/rust/subscription", json={"weight": -0.25})
    assert updated.status_code == 200
    assert updated.json()["weight"] == -0.25
    assert client.get("/tags/rust").json()["subscription"]["weight"] == -0.25

    assert client.delete("/tags/rust/subscribe").status_code == 204
    assert client.get("/tags/rust").json()["subscription"] is None
    assert client.get("/tag-subscriptions").json() == []
    assert client.delete("/tags/rust/subscribe").status_code == 404


def test_subscribe_through_an_alias_and_unknown_tags(client: TestClient) -> None:
    make_tag("Rust")
    with get_session_factory().begin() as session:
        session.execute(
            text(
                "INSERT INTO tag_aliases (alias, tag_id, source) "
                "SELECT 'rust-lang', id, 'user' FROM tags WHERE slug = 'rust'"
            )
        )

    assert client.post("/tags/rust-lang/subscribe").json()["slug"] == "rust"
    assert client.post("/tags/nope/subscribe").status_code == 404
    assert client.delete("/tags/nope/subscribe").status_code == 404
    assert client.patch("/tags/nope/subscription", json={"weight": 0}).status_code == 404


def test_update_needs_a_subscription_and_a_valid_weight(client: TestClient) -> None:
    make_tag()

    assert client.patch("/tags/rust/subscription", json={"weight": 0.2}).status_code == 404
    client.post("/tags/rust/subscribe")
    assert client.patch("/tags/rust/subscription", json={"weight": 2}).status_code == 422
    assert client.patch("/tags/rust/subscription", json={}).json()["weight"] == 0.5


def test_mute_and_unmute_a_tag(client: TestClient) -> None:
    make_tag()

    muted = client.post("/tags/rust/mute")

    assert muted.status_code == 200
    assert muted.json()["weight"] == -0.5
    assert client.post("/tags/rust/mute").json() == muted.json()  # idempotent
    assert client.get("/tags/rust").json()["subscription"]["weight"] == -0.5

    assert client.delete("/tags/rust/mute").status_code == 204
    assert client.get("/tags/rust").json()["subscription"] is None
    assert client.delete("/tags/rust/mute").status_code == 404
    assert client.post("/tags/nope/mute").status_code == 404
    assert client.delete("/tags/nope/mute").status_code == 404


def test_muting_flips_a_subscription_and_unmute_ignores_subscriptions(
    client: TestClient,
) -> None:
    make_tag()
    client.post("/tags/rust/subscribe")

    assert client.delete("/tags/rust/mute").status_code == 404  # a subscription, not a mute
    muted = client.post("/tags/rust/mute").json()

    assert muted["weight"] == -0.5
    assert [s["weight"] for s in client.get("/tag-subscriptions").json()] == [-0.5]


def test_hide_a_muted_tag_at_weight_minus_one(client: TestClient) -> None:
    make_tag()
    client.post("/tags/rust/mute")

    refused = client.patch("/tags/rust/subscription", json={"hide": True})
    assert refused.status_code == 422
    assert isinstance(refused.json()["detail"], str)
    hidden = client.patch("/tags/rust/subscription", json={"weight": -1, "hide": True})
    assert hidden.status_code == 200 and hidden.json()["hide"] is True
    assert client.get("/tags/rust").json()["subscription"]["hide"] is True

    raised = client.patch("/tags/rust/subscription", json={"weight": -0.4})
    assert raised.json()["hide"] is False
