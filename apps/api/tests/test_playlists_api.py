from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway.fake import make_channel, make_video
from homefeed_core.videos import store_video

A, B, C = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"


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


def create(client: TestClient, name: str, description: str = "") -> dict:
    response = client.post("/playlists", json={"name": name, "description": description})
    assert response.status_code == 201, response.text
    return response.json()


def add(client: TestClient, playlist_id: int, video_id: str, **body: int) -> dict:
    response = client.put(f"/playlists/{playlist_id}/items/{video_id}", json=body or None)
    assert response.status_code == 201, response.text
    return response.json()


def order(client: TestClient, playlist_id: int) -> list[str]:
    response = client.get(f"/playlists/{playlist_id}")
    assert response.status_code == 200
    return [item["video_id"] for item in response.json()["items"]]


def test_create_and_list(client: TestClient) -> None:
    later = create(client, " Watch later ", "weekend")
    create(client, "Blacksmithing")

    assert later == {
        "id": later["id"],
        "name": "Watch later",
        "description": "weekend",
        "item_count": 0,
        "thumbnail_url": None,
        "contains_video": None,
        "created_at": later["created_at"],
        "updated_at": later["created_at"],
    }
    response = client.get("/playlists")
    assert response.status_code == 200
    assert [p["name"] for p in response.json()] == ["Blacksmithing", "Watch later"]


def test_duplicate_name_is_409(client: TestClient) -> None:
    create(client, "Watch later")

    response = client.post("/playlists", json={"name": "WATCH LATER"})

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]


def test_blank_name_is_422_with_string_detail(client: TestClient) -> None:
    response = client.post("/playlists", json={"name": "   "})

    assert response.status_code == 422
    assert response.json()["detail"] == "Playlist name must not be blank"


def test_rename_and_describe(client: TestClient) -> None:
    playlist = create(client, "Later")
    create(client, "Weekend")
    path = f"/playlists/{playlist['id']}"

    renamed = client.patch(path, json={"name": "Someday"})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Someday"

    described = client.patch(path, json={"description": "maybe"})
    assert (described.json()["name"], described.json()["description"]) == ("Someday", "maybe")

    assert client.patch(path, json={"name": "weekend"}).status_code == 409
    assert client.patch("/playlists/99", json={"name": "x"}).status_code == 404


def test_delete(client: TestClient) -> None:
    playlist = create(client, "Later")
    add(client, playlist["id"], A)

    assert client.delete(f"/playlists/{playlist['id']}").status_code == 204
    assert client.delete(f"/playlists/{playlist['id']}").status_code == 404
    assert client.get(f"/playlists/{playlist['id']}").status_code == 404
    with get_session_factory()() as session:
        assert session.execute(text("SELECT count(*) FROM playlist_items")).scalar_one() == 0


def test_add_items_with_known_and_unknown_metadata(client: TestClient) -> None:
    channel = make_channel("UC" + "w" * 22, title="Wood")
    with get_session_factory().begin() as session:
        store_video(session, make_video(A, channel=channel, title="Hand planes"))
    playlist = create(client, "Later")

    item = add(client, playlist["id"], A)
    add(client, playlist["id"], B)

    assert item["video_id"] == A
    assert item["position"] == 0
    assert item["title"] == "Hand planes"
    assert item["channel_title"] == "Wood"
    detail = client.get(f"/playlists/{playlist['id']}").json()
    assert detail["playlist"]["item_count"] == 2
    assert [(i["video_id"], i["title"]) for i in detail["items"]] == [
        (A, "Hand planes"),
        (B, None),
    ]


def test_adding_again_returns_200(client: TestClient) -> None:
    playlist = create(client, "Later")
    first = add(client, playlist["id"], A)

    response = client.put(f"/playlists/{playlist['id']}/items/{A}")

    assert response.status_code == 200
    assert response.json() == first


def test_add_at_position(client: TestClient) -> None:
    playlist = create(client, "Later")
    add(client, playlist["id"], A)
    add(client, playlist["id"], B)

    add(client, playlist["id"], C, position=0)

    assert order(client, playlist["id"]) == [C, A, B]


def test_add_errors(client: TestClient) -> None:
    playlist = create(client, "Later")

    assert client.put(f"/playlists/99/items/{A}").status_code == 404
    assert client.put(f"/playlists/{playlist['id']}/items/short").status_code == 422
    response = client.put(f"/playlists/{playlist['id']}/items/{A}", json={"position": -1})
    assert response.status_code == 422


def test_move_and_remove(client: TestClient) -> None:
    playlist = create(client, "Later")
    for video_id in (A, B, C):
        add(client, playlist["id"], video_id)
    items = f"/playlists/{playlist['id']}/items"

    moved = client.patch(f"{items}/{A}", json={"position": 2})
    assert moved.status_code == 200
    assert moved.json()["position"] == 2
    assert order(client, playlist["id"]) == [B, C, A]

    assert client.delete(f"{items}/{C}").status_code == 204
    assert order(client, playlist["id"]) == [B, A]
    assert client.delete(f"{items}/{C}").status_code == 404
    assert client.patch(f"{items}/{C}", json={"position": 0}).status_code == 404


def test_list_with_video_id_says_which_contain_it(client: TestClient) -> None:
    later = create(client, "Later")
    create(client, "Weekend")
    add(client, later["id"], A)

    response = client.get("/playlists", params={"video_id": A})

    assert [(p["name"], p["contains_video"]) for p in response.json()] == [
        ("Later", True),
        ("Weekend", False),
    ]
    assert client.get("/playlists", params={"video_id": "bad"}).status_code == 422
