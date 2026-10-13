from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory

NEWEST = {"sort": "upload_date", "upload_date": "week", "duration": None}
DEFAULT_FILTERS = {"sort": "relevance", "upload_date": None, "duration": None}


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


def save(client: TestClient, body: dict) -> dict:
    response = client.post("/saved-searches", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def stored() -> list[tuple]:
    with get_session_factory()() as session:
        return [
            tuple(row)
            for row in session.execute(
                text("SELECT query, filters, schedule FROM saved_searches ORDER BY id")
            )
        ]


def test_save_and_list(client: TestClient) -> None:
    wood = save(client, {"query": "  hand   planes ", "filters": NEWEST, "schedule": "weekly"})
    save(client, {"query": "Blacksmithing"})

    assert wood == {
        "id": wood["id"],
        "query": "hand planes",
        "filters": NEWEST,
        "schedule": "weekly",
        "next_run_at": wood["created_at"],
        "last_run_at": None,
        "last_found_count": None,
        "last_error": None,
        "created_at": wood["created_at"],
        "updated_at": wood["updated_at"],
    }
    response = client.get("/saved-searches")
    assert response.status_code == 200
    assert [(s["query"], s["filters"], s["schedule"]) for s in response.json()] == [
        ("Blacksmithing", DEFAULT_FILTERS, "daily"),
        ("hand planes", NEWEST, "weekly"),
    ]
    assert stored() == [
        ("hand planes", '{"sort":"upload_date","upload_date":"week"}', "weekly"),
        ("Blacksmithing", "{}", "daily"),
    ]


def test_saving_again_returns_200_with_the_existing_search(client: TestClient) -> None:
    wood = save(client, {"query": "Hand planes", "filters": NEWEST})

    response = client.post(
        "/saved-searches", json={"query": "HAND PLANES", "filters": NEWEST, "schedule": "paused"}
    )

    assert response.status_code == 200
    assert response.json() == wood
    assert len(stored()) == 1


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"query": ""},
        {"query": "x" * 201},
        {"query": "wood", "schedule": "hourly"},
        {"query": "wood", "filters": {"sort": "newest"}},
    ],
)
def test_save_validates_body(client: TestClient, body: dict) -> None:
    assert client.post("/saved-searches", json=body).status_code == 422


def test_save_blank_query_is_422_with_a_message(client: TestClient) -> None:
    response = client.post("/saved-searches", json={"query": "   "})

    assert response.status_code == 422
    assert response.json() == {"detail": "Search query is empty"}


def test_update(client: TestClient) -> None:
    wood = save(client, {"query": "wood"})

    paused = client.patch(f"/saved-searches/{wood['id']}", json={"schedule": "paused"})
    renamed = client.patch(
        f"/saved-searches/{wood['id']}", json={"query": "woodworking", "filters": NEWEST}
    )

    assert paused.status_code == 200, paused.text
    assert (paused.json()["schedule"], paused.json()["next_run_at"]) == ("paused", None)
    assert renamed.status_code == 200, renamed.text
    assert (renamed.json()["query"], renamed.json()["filters"], renamed.json()["schedule"]) == (
        "woodworking",
        NEWEST,
        "paused",
    )


def test_update_to_an_existing_search_is_409(client: TestClient) -> None:
    save(client, {"query": "wood"})
    metal = save(client, {"query": "metal"})

    response = client.patch(f"/saved-searches/{metal['id']}", json={"query": "Wood"})

    assert response.status_code == 409
    assert stored()[1][0] == "metal"


def test_update_missing_search_is_404(client: TestClient) -> None:
    response = client.patch("/saved-searches/99", json={"schedule": "weekly"})
    assert response.status_code == 404


def test_update_blank_query_is_422(client: TestClient) -> None:
    wood = save(client, {"query": "wood"})
    assert client.patch(f"/saved-searches/{wood['id']}", json={"query": " "}).status_code == 422


def test_delete(client: TestClient) -> None:
    wood = save(client, {"query": "wood"})

    assert client.delete(f"/saved-searches/{wood['id']}").status_code == 204
    assert client.delete(f"/saved-searches/{wood['id']}").status_code == 404
    assert client.get("/saved-searches").json() == []


def test_rejects_invalid_ids(client: TestClient) -> None:
    assert client.delete("/saved-searches/0").status_code == 422
    assert client.patch("/saved-searches/abc", json={}).status_code == 422
