from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory

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


def stored_ratings() -> list[tuple[str, int, float]]:
    with get_session_factory()() as session:
        rows = session.execute(text("SELECT video_id, score, value FROM ratings")).all()
    return [tuple(row) for row in rows]


def test_put_creates_rating(client: TestClient) -> None:
    response = client.put(f"/ratings/{VIDEO_ID}", json={"score": 6})

    assert response.status_code == 200
    body = response.json()
    assert body["video_id"] == VIDEO_ID
    assert body["score"] == 6 and isinstance(body["score"], int)
    assert body["value"] == pytest.approx((6 - 5.5) / 4.5)
    assert body["rated_at"] == body["updated_at"]
    assert stored_ratings() == [(VIDEO_ID, 6, pytest.approx(body["value"]))]


def test_put_updates_existing_rating(client: TestClient) -> None:
    created = client.put(f"/ratings/{VIDEO_ID}", json={"score": 4}).json()

    response = client.put(f"/ratings/{VIDEO_ID}", json={"score": 10})

    assert response.status_code == 200
    body = response.json()
    assert body["score"] == 10
    assert body["value"] == 1.0
    assert body["rated_at"] == created["rated_at"]
    assert stored_ratings() == [(VIDEO_ID, 10, 1.0)]


@pytest.mark.parametrize("score", range(1, 11))
def test_put_accepts_whole_scores(client: TestClient, score: int) -> None:
    response = client.put(f"/ratings/{VIDEO_ID}", json={"score": score})
    assert response.status_code == 200
    assert response.json()["score"] == score


def test_put_accepts_a_whole_valued_float_as_that_score(client: TestClient) -> None:
    response = client.put(f"/ratings/{VIDEO_ID}", json={"score": 7.0})
    assert response.status_code == 200
    assert response.json()["score"] == 7
    assert stored_ratings() == [(VIDEO_ID, 7, pytest.approx((7 - 5.5) / 4.5))]


@pytest.mark.parametrize(
    "body",
    [
        {"score": 0},
        {"score": 11},
        {"score": -3},
        {"score": 0.9},
        {"score": 10.1},
        {"score": 7.5},
        {"score": 4.25},
        {"score": True},
        {"score": "seven"},
        {"score": None},
        {"grade": "A"},
        {},
    ],
)
def test_put_rejects_invalid_score(client: TestClient, body: dict[str, object]) -> None:
    assert client.put(f"/ratings/{VIDEO_ID}", json=body).status_code == 422
    assert stored_ratings() == []


@pytest.mark.parametrize("video_id", ["short", "dQw4w9WgXcQx", "dQw4w9WgXc!"])
def test_put_rejects_invalid_video_id(client: TestClient, video_id: str) -> None:
    assert client.put(f"/ratings/{video_id}", json={"score": 6}).status_code == 422


def test_delete_removes_rating(client: TestClient) -> None:
    client.put(f"/ratings/{VIDEO_ID}", json={"score": 8})

    response = client.delete(f"/ratings/{VIDEO_ID}")

    assert response.status_code == 204
    assert response.content == b""
    assert stored_ratings() == []


def test_delete_missing_rating_is_404(client: TestClient) -> None:
    assert client.delete(f"/ratings/{VIDEO_ID}").status_code == 404


def test_openapi_bounds_the_score(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    score = schema["components"]["schemas"]["RatingInput"]["properties"]["score"]
    assert (score["minimum"], score["maximum"]) == (1, 10)
    assert score["type"] == "integer"


def test_get_returns_rating(client: TestClient) -> None:
    created = client.put(f"/ratings/{VIDEO_ID}", json={"score": 8}).json()

    response = client.get(f"/ratings/{VIDEO_ID}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_missing_rating_is_404(client: TestClient) -> None:
    response = client.get(f"/ratings/{VIDEO_ID}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Rating not found"}
