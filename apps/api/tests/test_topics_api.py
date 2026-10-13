from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app, get_embedder
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.embeddings import StubEmbeddingProvider
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.tags import resolve_tag


@pytest.fixture
def embedder() -> StubEmbeddingProvider:
    return StubEmbeddingProvider()


@pytest.fixture
def client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, embedder: StubEmbeddingProvider
) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    app.dependency_overrides[get_embedder] = lambda: embedder
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def create(client: TestClient, **fields: object) -> dict:
    body = {"name": "Woodworking", "description": "Hand tool woodworking", "weight": 0.5}
    response = client.post("/topics", json={**body, **fields})
    assert response.status_code == 201, response.text
    return response.json()


def stored() -> list[tuple[str, float, int]]:
    with get_session_factory()() as session:
        rows = session.execute(text("SELECT name, weight, decay FROM topics ORDER BY id"))
        return [tuple(row) for row in rows]


def test_create_and_list(client: TestClient, embedder: StubEmbeddingProvider) -> None:
    wood = create(client, name=" Woodworking ", description=" Hand tool woodworking ")
    drama = create(client, name="drama", description="Influencer drama", weight=-1, decay=True)

    assert wood == {
        "id": wood["id"],
        "name": "Woodworking",
        "description": "Hand tool woodworking",
        "weight": 0.5,
        "decay": False,
        "effective_weight": 0.5,
        "reaffirmed_at": wood["created_at"],
        "created_at": wood["created_at"],
        "updated_at": wood["created_at"],
        "match_mode": "embedding",
        "tag_id": None,
        "tag_slug": None,
        "tag_label": None,
        "hide": False,
    }
    assert drama["decay"] is True
    assert drama["effective_weight"] == pytest.approx(-1.0)
    assert embedder.calls == [["Hand tool woodworking"], ["Influencer drama"]]
    response = client.get("/topics")
    assert response.status_code == 200
    assert [t["name"] for t in response.json()] == ["drama", "Woodworking"]


def test_duplicate_names_conflict(client: TestClient) -> None:
    create(client, name="Woodworking")
    birds = create(client, name="Birds")

    response = client.post("/topics", json={"name": "WOODWORKING", "description": "x", "weight": 1})
    assert response.status_code == 409
    assert response.json() == {"detail": "There is already a topic named 'WOODWORKING'"}
    response = client.patch(f"/topics/{birds['id']}", json={"name": "woodworking"})
    assert response.status_code == 409
    assert stored() == [("Woodworking", 0.5, 0), ("Birds", 0.5, 0)]


@pytest.mark.parametrize(
    "fields",
    [
        {"name": ""},
        {"name": "x" * 61},
        {"description": ""},
        {"description": "x" * 501},
        {"weight": 1.5},
        {"weight": -1.01},
    ],
)
def test_create_rejects_invalid_fields(client: TestClient, fields: dict[str, object]) -> None:
    body = {"name": "Woodworking", "description": "wood", "weight": 0.5, **fields}

    assert client.post("/topics", json=body).status_code == 422
    assert stored() == []


def test_blank_name_detail_is_a_string(client: TestClient) -> None:
    response = client.post("/topics", json={"name": "  ", "description": "wood", "weight": 0})

    assert response.status_code == 422
    assert response.json() == {"detail": "Topic name is empty"}


def test_update(client: TestClient, embedder: StubEmbeddingProvider) -> None:
    wood = create(client)

    response = client.patch(
        f"/topics/{wood['id']}", json={"weight": -0.25, "decay": True, "description": "Joinery"}
    )

    assert response.status_code == 200
    updated = response.json()
    assert (updated["weight"], updated["decay"], updated["description"]) == (-0.25, True, "Joinery")
    assert updated["name"] == "Woodworking"
    assert embedder.calls[-1] == ["Joinery"]
    assert client.patch("/topics/999", json={"weight": 0}).status_code == 404
    assert client.patch(f"/topics/{wood['id']}", json={"weight": 2}).status_code == 422
    assert stored() == [("Woodworking", -0.25, 1)]


def test_reaffirm_restores_a_decayed_weight(client: TestClient) -> None:
    wood = create(client, weight=0.8, decay=True)
    month_ago = format_timestamp(datetime.now(UTC) - timedelta(days=30))
    with get_session_factory().begin() as session:
        session.execute(text("UPDATE topics SET reaffirmed_at = :at"), {"at": month_ago})
    [decayed] = client.get("/topics").json()
    assert decayed["effective_weight"] == pytest.approx(0.4, abs=1e-3)

    response = client.post(f"/topics/{wood['id']}/reaffirm")

    assert response.status_code == 200
    assert response.json()["effective_weight"] == pytest.approx(0.8, abs=1e-3)
    assert response.json()["reaffirmed_at"] > month_ago
    assert client.post("/topics/999/reaffirm").status_code == 404


def test_delete(client: TestClient) -> None:
    wood = create(client)

    assert client.delete(f"/topics/{wood['id']}").status_code == 204
    assert client.delete(f"/topics/{wood['id']}").status_code == 404
    assert client.delete("/topics/0").status_code == 422
    assert stored() == []


def make_tag(label: str = "Rust") -> int:
    with get_session_factory().begin() as session:
        tag = resolve_tag(session, label)
        assert tag is not None
        return tag.id


def test_subscribe_creates_a_tag_backed_topic_and_shows_on_the_tag_page(
    client: TestClient,
) -> None:
    tag_id = make_tag()
    assert client.get("/tags/rust").json()["topic"] is None

    response = client.post("/tags/rust/subscribe")

    assert response.status_code == 200
    topic = response.json()
    assert (topic["name"], topic["description"], topic["weight"]) == ("Rust", "Rust", 0.5)
    assert (topic["match_mode"], topic["tag_id"], topic["tag_slug"]) == ("tag", tag_id, "rust")
    assert client.post("/tags/rust/subscribe").json()["id"] == topic["id"]  # idempotent
    assert client.get("/tags/rust").json()["topic"] == {
        "id": topic["id"],
        "weight": 0.5,
        "effective_weight": 0.5,
        "decay": False,
        "match_mode": "tag",
        "hide": False,
    }
    assert [t["id"] for t in client.get("/topics").json()] == [topic["id"]]

    updated = client.patch(
        f"/topics/{topic['id']}", json={"weight": -0.25, "match_mode": "both", "decay": True}
    )
    assert updated.status_code == 200
    assert client.get("/tags/rust").json()["topic"] == {
        "id": topic["id"],
        "weight": -0.25,
        "effective_weight": pytest.approx(-0.25),
        "decay": True,
        "match_mode": "both",
        "hide": False,
    }

    assert client.delete("/tags/rust/subscribe").status_code == 204
    assert client.get("/tags/rust").json()["topic"] is None
    assert client.get("/topics").json() == []
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

    assert client.post("/tags/rust-lang/subscribe").json()["tag_slug"] == "rust"
    assert client.post("/tags/nope/subscribe").status_code == 404
    assert client.delete("/tags/nope/subscribe").status_code == 404


def test_create_a_topic_for_a_tag(client: TestClient) -> None:
    make_tag()

    topic = create(client, name="Rust stuff", tag="rust", weight=0.3, description=None)

    assert (topic["description"], topic["match_mode"], topic["tag_slug"]) == ("Rust", "tag", "rust")
    both = client.patch(f"/topics/{topic['id']}", json={"match_mode": "both"}).json()
    assert both["match_mode"] == "both"
    taken = client.post("/topics", json={"name": "Other", "tag": "rust", "weight": 0.1})
    assert taken.status_code == 409


def test_topic_validation_for_tags_and_modes(client: TestClient) -> None:
    make_tag()
    plain = create(client)

    for body in [
        {"name": "x", "weight": 0.1},  # no description, no tag
        {"name": "x", "weight": 0.1, "tag": "nope"},
        {"name": "x", "description": "x", "weight": 0.1, "match_mode": "tag"},
        {"name": "x", "weight": 0.1, "tag": "rust", "match_mode": "bogus"},
    ]:
        assert client.post("/topics", json=body).status_code == 422, body
    assert client.patch(f"/topics/{plain['id']}", json={"match_mode": "both"}).status_code == 422


def test_mute_and_unmute_a_tag(client: TestClient) -> None:
    make_tag()

    topic = client.post("/tags/rust/mute")

    assert topic.status_code == 200
    assert (topic.json()["weight"], topic.json()["match_mode"]) == (-0.5, "tag")
    assert client.post("/tags/rust/mute").json()["id"] == topic.json()["id"]  # idempotent
    assert client.get("/tags/rust").json()["topic"]["weight"] == -0.5

    assert client.delete("/tags/rust/mute").status_code == 204
    assert client.get("/tags/rust").json()["topic"] is None
    assert client.delete("/tags/rust/mute").status_code == 404
    assert client.post("/tags/nope/mute").status_code == 404
    assert client.delete("/tags/nope/mute").status_code == 404


def test_muting_flips_a_subscription_and_unmute_ignores_subscriptions(
    client: TestClient,
) -> None:
    make_tag()
    subscribed = client.post("/tags/rust/subscribe").json()

    assert client.delete("/tags/rust/mute").status_code == 404  # a subscription, not a mute
    muted = client.post("/tags/rust/mute").json()

    assert muted["id"] == subscribed["id"] and muted["weight"] == -0.5


def test_hide_a_muted_tag_at_weight_minus_one(client: TestClient) -> None:
    make_tag()
    plain = create(client)
    topic = client.post("/tags/rust/mute").json()

    assert client.patch(f"/topics/{topic['id']}", json={"hide": True}).status_code == 422
    assert client.patch(f"/topics/{plain['id']}", json={"hide": True}).status_code == 422
    hidden = client.patch(f"/topics/{topic['id']}", json={"weight": -1, "hide": True})
    assert hidden.status_code == 200 and hidden.json()["hide"] is True
    assert client.get("/tags/rust").json()["topic"]["hide"] is True

    raised = client.patch(f"/topics/{topic['id']}", json={"weight": -0.4})
    assert raised.json()["hide"] is False
