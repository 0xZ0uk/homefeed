from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from homefeed_api.main import app, get_gateway
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway import RateLimitedError, SearchFilters
from homefeed_core.gateway.fake import FakeGateway, make_channel, make_video

WOOD = make_channel("UC" + "w" * 22, title="Woodworking", handle="@wood")


@pytest.fixture
def gateway() -> FakeGateway:
    gateway = FakeGateway()
    gateway.add_search(
        "hand planes",
        [
            make_video(
                "aaaaaaaaaaa",
                channel=WOOD,
                title="Tuning a hand plane",
                description="Flatten the sole",
                duration_seconds=900,
                view_count=1200,
                thumbnail_url="https://example.invalid/a.jpg",
            ),
            make_video("bbbbbbbbbbb", channel=WOOD, title="Plane irons"),
        ],
    )
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


def test_search(client: TestClient, gateway: FakeGateway) -> None:
    response = client.get("/search", params={"q": " hand  planes "})

    assert response.status_code == 200, response.text
    first, second = response.json()
    assert first == {
        "id": "aaaaaaaaaaa",
        "title": "Tuning a hand plane",
        "channel_id": WOOD.id,
        "channel_title": "Woodworking",
        "channel_handle": "@wood",
        "description": "Flatten the sole",
        "duration_seconds": 900,
        "view_count": 1200,
        "thumbnail_url": "https://example.invalid/a.jpg",
        "live_status": "not_live",
    }
    assert second["id"] == "bbbbbbbbbbb"
    assert gateway.searches == [("hand planes", SearchFilters())]


def test_search_with_filters_and_limit(client: TestClient, gateway: FakeGateway) -> None:
    response = client.get(
        "/search",
        params={
            "q": "hand planes",
            "sort": "upload_date",
            "upload_date": "week",
            "duration": "long",
            "limit": 1,
        },
    )

    assert response.status_code == 200, response.text
    assert [video["id"] for video in response.json()] == ["aaaaaaaaaaa"]
    assert gateway.searches == [
        ("hand planes", SearchFilters(sort="upload_date", upload_date="week", duration="long"))
    ]


def test_search_without_results(client: TestClient) -> None:
    response = client.get("/search", params={"q": "nothing here"})

    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.parametrize(
    "params",
    [
        {},
        {"q": ""},
        {"q": "x" * 201},
        {"q": "wood", "sort": "newest"},
        {"q": "wood", "upload_date": "decade"},
        {"q": "wood", "duration": "epic"},
        {"q": "wood", "limit": 0},
        {"q": "wood", "limit": 51},
    ],
)
def test_search_validates_parameters(client: TestClient, params: dict) -> None:
    assert client.get("/search", params=params).status_code == 422


def test_search_blank_query_is_422_with_a_message(client: TestClient) -> None:
    response = client.get("/search", params={"q": "   "})

    assert response.status_code == 422
    assert response.json() == {"detail": "Search query is empty"}


def test_search_gateway_failure_is_502(client: TestClient, gateway: FakeGateway) -> None:
    gateway.fail("search", "hand planes", RateLimitedError("HTTP Error 429"))

    response = client.get("/search", params={"q": "hand planes"})

    assert response.status_code == 502
    assert response.json() == {"detail": "HTTP Error 429"}
