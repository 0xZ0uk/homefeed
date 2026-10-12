from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.grades import GRADES

VIDEO_ID = "dQw4w9WgXcQ"


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


def stored_ratings() -> list[tuple[str, str, float]]:
    with get_session_factory()() as session:
        rows = session.execute(text("SELECT video_id, grade, value FROM ratings")).all()
    return [tuple(row) for row in rows]


def test_put_creates_rating(client: TestClient) -> None:
    response = client.put(f"/ratings/{VIDEO_ID}", json={"grade": "B"})

    assert response.status_code == 200
    body = response.json()
    assert body["video_id"] == VIDEO_ID
    assert body["grade"] == "B"
    assert body["value"] == pytest.approx(-1 + 2 * 17 / 29)
    assert body["rated_at"] == body["updated_at"]
    assert stored_ratings() == [(VIDEO_ID, "B", pytest.approx(body["value"]))]


def test_put_updates_existing_rating(client: TestClient) -> None:
    created = client.put(f"/ratings/{VIDEO_ID}", json={"grade": "C-"}).json()

    response = client.put(f"/ratings/{VIDEO_ID}", json={"grade": "S++"})

    assert response.status_code == 200
    body = response.json()
    assert body["grade"] == "S++"
    assert body["value"] == 1.0
    assert body["rated_at"] == created["rated_at"]
    assert stored_ratings() == [(VIDEO_ID, "S++", 1.0)]


@pytest.mark.parametrize("grade", GRADES)
def test_put_accepts_every_grade(client: TestClient, grade: str) -> None:
    assert client.put(f"/ratings/{VIDEO_ID}", json={"grade": grade}).status_code == 200


@pytest.mark.parametrize("body", [{"grade": "B+++"}, {"grade": "b"}, {"grade": ""}, {}])
def test_put_rejects_invalid_grade(client: TestClient, body: dict[str, str]) -> None:
    assert client.put(f"/ratings/{VIDEO_ID}", json=body).status_code == 422
    assert stored_ratings() == []


@pytest.mark.parametrize("video_id", ["short", "dQw4w9WgXcQx", "dQw4w9WgXc!"])
def test_put_rejects_invalid_video_id(client: TestClient, video_id: str) -> None:
    assert client.put(f"/ratings/{video_id}", json={"grade": "B"}).status_code == 422


def test_delete_removes_rating(client: TestClient) -> None:
    client.put(f"/ratings/{VIDEO_ID}", json={"grade": "A"})

    response = client.delete(f"/ratings/{VIDEO_ID}")

    assert response.status_code == 204
    assert response.content == b""
    assert stored_ratings() == []


def test_delete_missing_rating_is_404(client: TestClient) -> None:
    assert client.delete(f"/ratings/{VIDEO_ID}").status_code == 404


def test_openapi_lists_grades_as_enum(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    grade = schema["components"]["schemas"]["RatingInput"]["properties"]["grade"]
    assert grade["enum"] == list(GRADES)


def test_get_returns_rating(client: TestClient) -> None:
    created = client.put(f"/ratings/{VIDEO_ID}", json={"grade": "A+"}).json()

    response = client.get(f"/ratings/{VIDEO_ID}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_rating_is_404(client: TestClient) -> None:
    response = client.get(f"/ratings/{VIDEO_ID}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Rating not found"}
