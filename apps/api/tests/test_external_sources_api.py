from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory


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


def add(client: TestClient, **body: object) -> dict:
    response = client.post("/external-sources", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def stored() -> list[tuple[str, str, str]]:
    with get_session_factory()() as session:
        rows = session.execute(text("SELECT kind, url, schedule FROM external_sources ORDER BY id"))
        return [tuple(row) for row in rows]


def test_add_and_list(client: TestClient) -> None:
    reddit = add(client, kind="subreddit", url="r/Documentaries", schedule="hourly")
    feed = add(client, kind="rss", url="example.com/feed.xml")

    assert reddit == {
        "id": reddit["id"],
        "kind": "subreddit",
        "url": "https://www.reddit.com/r/Documentaries",
        "label": "r/Documentaries",
        "title": None,
        "schedule": "hourly",
        "next_fetch_at": reddit["next_fetch_at"],
        "last_fetched_at": None,
        "last_success_at": None,
        "consecutive_failures": 0,
        "last_error": None,
        "last_found_count": None,
        "created_at": reddit["created_at"],
        "updated_at": reddit["updated_at"],
    }
    assert (feed["url"], feed["label"], feed["schedule"]) == (
        "https://example.com/feed.xml",
        "example.com/feed.xml",
        "daily",
    )
    response = client.get("/external-sources")
    assert response.status_code == 200
    assert [s["id"] for s in response.json()] == [feed["id"], reddit["id"]]


def test_adding_again_returns_200_with_the_existing_source(client: TestClient) -> None:
    reddit = add(client, kind="subreddit", url="r/videos")

    response = client.post(
        "/external-sources",
        json={"kind": "subreddit", "url": "https://old.reddit.com/r/Videos/", "schedule": "weekly"},
    )

    assert response.status_code == 200
    assert response.json() == reddit
    assert stored() == [("subreddit", "https://www.reddit.com/r/videos", "daily")]


@pytest.mark.parametrize(
    ("body", "detail"),
    [
        (
            {"kind": "rss", "url": "https://www.youtube.com/@channel"},
            "YouTube links can't be external sources; subscribe to the channel instead",
        ),
        ({"kind": "subreddit", "url": "r/"}, "Not a subreddit name: 'r'"),
        ({"kind": "page", "url": "   "}, "URL is empty"),
    ],
)
def test_invalid_urls_are_422_with_a_string_detail(
    client: TestClient, body: dict, detail: str
) -> None:
    response = client.post("/external-sources", json=body)

    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    assert stored() == []


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "twitter", "url": "https://example.com"},
        {"kind": "rss", "url": "https://example.com", "schedule": "monthly"},
        {"kind": "rss", "url": ""},
    ],
)
def test_request_validation(client: TestClient, body: dict) -> None:
    assert client.post("/external-sources", json=body).status_code == 422


def test_update_schedule(client: TestClient) -> None:
    feed = add(client, kind="rss", url="https://example.com/feed")

    response = client.patch(f"/external-sources/{feed['id']}", json={"schedule": "weekly"})
    assert response.status_code == 200
    assert response.json()["schedule"] == "weekly"

    response = client.patch(f"/external-sources/{feed['id']}", json={})
    assert response.status_code == 200
    assert response.json()["schedule"] == "weekly"

    assert (
        client.patch(f"/external-sources/{feed['id']}", json={"schedule": "x"}).status_code == 422
    )
    assert client.patch("/external-sources/999", json={"schedule": "daily"}).status_code == 404
    assert stored() == [("rss", "https://example.com/feed", "weekly")]


def test_delete(client: TestClient) -> None:
    feed = add(client, kind="page", url="https://example.com/links")

    assert client.delete(f"/external-sources/{feed['id']}").status_code == 204
    assert client.delete(f"/external-sources/{feed['id']}").status_code == 404
    assert client.delete("/external-sources/0").status_code == 422
    assert stored() == []
