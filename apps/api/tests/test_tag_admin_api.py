from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app, get_embedder
from homefeed_core import tags
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.embeddings import StubEmbeddingProvider

VIDEO = "aaaaaaaaaaa"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    app.dependency_overrides[get_embedder] = lambda: StubEmbeddingProvider()
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def make_tag(label: str, *, videos: int = 0, alias: str | None = None) -> int:
    with get_session_factory().begin() as session:
        tag = tags.resolve_tag(session, label)
        assert tag is not None
        if videos:
            session.execute(text("INSERT OR IGNORE INTO channels (id, title) VALUES ('UCx', 'C')"))
            session.execute(
                text(
                    "INSERT OR IGNORE INTO videos (id, channel_id, title) VALUES (:v, 'UCx', 't')"
                ),
                {"v": VIDEO},
            )
            session.execute(
                text(
                    "INSERT INTO video_tags (video_id, tag_id, source, confidence) "
                    "VALUES (:v, :t, 'llm', 0.5)"
                ),
                {"v": VIDEO, "t": tag.id},
            )
        if alias:
            session.execute(
                text("INSERT INTO tag_aliases (alias, tag_id, source) VALUES (:a, :t, 'auto')"),
                {"a": alias, "t": tag.id},
            )
        return tag.id


def test_list_with_counts_aliases_and_search(client: TestClient) -> None:
    make_tag("Rust", videos=1, alias="rust-lang")
    make_tag("Woodworking")

    listed = client.get("/tag-admin").json()
    assert [(t["slug"], t["video_count"]) for t in listed] == [("rust", 1), ("woodworking", 0)]
    assert listed[0]["aliases"] == [{"alias": "rust-lang", "source": "auto"}]
    assert [t["slug"] for t in client.get("/tag-admin", params={"q": "lang"}).json()] == ["rust"]
    assert client.get("/tag-admin", params={"limit": 0}).status_code == 422


def test_list_shows_and_filters_by_subscription(client: TestClient) -> None:
    make_tag("Rust", videos=1)
    make_tag("Woodworking")
    make_tag("Drama")
    client.post("/tags/woodworking/subscribe")
    client.post("/tags/drama/mute")

    def listed(**params: str) -> list[tuple[str, float | None]]:
        response = client.get("/tag-admin", params=params)
        return [(t["slug"], t["subscription_weight"]) for t in response.json()]

    assert listed() == [("rust", None), ("drama", -0.5), ("woodworking", 0.5)]
    assert listed(subscription="subscribed") == [("woodworking", 0.5)]
    assert listed(subscription="muted") == [("drama", -0.5)]
    assert listed(subscription="muted", q="wood") == []
    assert client.get("/tag-admin", params={"subscription": "nope"}).status_code == 422


def test_rename(client: TestClient) -> None:
    tag_id = make_tag("Wood work")
    other = make_tag("Rust")

    response = client.patch(f"/tag-admin/{tag_id}", json={"label": "Woodworking"})
    assert response.status_code == 200
    assert response.json() == {"id": tag_id, "slug": "woodworking", "label": "Woodworking"}
    assert client.get("/tag-admin", params={"q": "wood-work"}).json()[0]["aliases"] == [
        {"alias": "wood-work", "source": "user"}
    ]
    assert client.patch(f"/tag-admin/{tag_id}", json={"label": "rust"}).status_code == 409
    assert client.patch(f"/tag-admin/{tag_id}", json={"label": "!!!"}).status_code == 422
    assert client.patch(f"/tag-admin/{tag_id}", json={"label": ""}).status_code == 422
    assert client.patch("/tag-admin/999", json={"label": "x"}).status_code == 404
    assert other != tag_id


def test_merge(client: TestClient) -> None:
    source = make_tag("Node", videos=1)
    target = make_tag("JavaScript")

    response = client.post(f"/tag-admin/{source}/merge", json={"target_id": target})
    assert response.status_code == 200
    assert response.json()["slug"] == "javascript"
    listed = client.get("/tag-admin").json()
    assert [(t["slug"], t["video_count"]) for t in listed] == [("javascript", 1)]
    assert listed[0]["aliases"] == [{"alias": "node", "source": "user"}]
    assert client.post(f"/tag-admin/{target}/merge", json={"target_id": target}).status_code == 422
    assert client.post(f"/tag-admin/{target}/merge", json={"target_id": 999}).status_code == 404
    assert client.post("/tag-admin/999/merge", json={"target_id": target}).status_code == 404


def test_split(client: TestClient) -> None:
    make_tag("JavaScript", videos=1, alias="node-js")

    response = client.post("/tag-admin/aliases/node-js/split")
    assert response.status_code == 201
    assert response.json()["slug"] == "node-js"
    listed = client.get("/tag-admin").json()
    assert {t["slug"]: t["aliases"] for t in listed} == {"javascript": [], "node-js": []}
    assert client.post("/tag-admin/aliases/node-js/split").status_code == 404
