from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from homefeed_api.main import app, get_gateway
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway.fake import FakeGateway, make_channel

WOOD = make_channel("UC" + "w" * 22, title="Woodworking", handle="@wood")


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    gateway = FakeGateway()
    gateway.add_channel(WOOD)
    app.dependency_overrides[get_gateway] = lambda: gateway
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def test_fresh_install_needs_onboarding(client: TestClient) -> None:
    response = client.get("/onboarding")
    assert response.status_code == 200
    assert response.json() == {"completed": False, "subscribed_channels": 0, "needed": True}


def test_subscribing_means_it_is_not_needed(client: TestClient) -> None:
    client.post("/channels", json={"url": "https://www.youtube.com/@wood"})
    assert client.get("/onboarding").json() == {
        "completed": False,
        "subscribed_channels": 1,
        "needed": False,
    }


def test_completing_is_remembered_and_repeatable(client: TestClient) -> None:
    for _ in range(2):
        response = client.post("/onboarding/complete")
        assert response.status_code == 200
        assert response.json() == {"completed": True, "subscribed_channels": 0, "needed": False}
    assert client.get("/onboarding").json()["completed"] is True


def test_completion_survives_unsubscribing(client: TestClient) -> None:
    client.post("/channels", json={"url": "https://www.youtube.com/@wood"})
    client.post("/onboarding/complete")
    client.delete(f"/channels/{WOOD.id}")
    assert client.get("/onboarding").json() == {
        "completed": True,
        "subscribed_channels": 0,
        "needed": False,
    }
