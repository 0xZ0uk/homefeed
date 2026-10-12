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


def mute(client: TestClient, keyword: str) -> dict:
    response = client.post("/keyword-mutes", json={"keyword": keyword})
    assert response.status_code == 201, response.text
    return response.json()


def stored() -> list[str]:
    with get_session_factory()() as session:
        return list(
            session.execute(text("SELECT keyword FROM keyword_mutes ORDER BY id")).scalars()
        )


def test_mute_and_list(client: TestClient) -> None:
    crypto = mute(client, "  crypto ")
    mute(client, "Reaction video")

    assert crypto == {"id": crypto["id"], "keyword": "crypto", "created_at": crypto["created_at"]}
    response = client.get("/keyword-mutes")
    assert response.status_code == 200
    assert [m["keyword"] for m in response.json()] == ["crypto", "Reaction video"]
    assert stored() == ["crypto", "Reaction video"]


def test_muting_again_returns_200_with_the_existing_mute(client: TestClient) -> None:
    crypto = mute(client, "Crypto")

    response = client.post("/keyword-mutes", json={"keyword": "CRYPTO"})

    assert response.status_code == 200
    assert response.json() == crypto
    assert stored() == ["Crypto"]


@pytest.mark.parametrize("keyword", ["", "   ", "x" * 101])
def test_mute_rejects_blank_and_long_keywords(client: TestClient, keyword: str) -> None:
    response = client.post("/keyword-mutes", json={"keyword": keyword})

    assert response.status_code == 422
    assert stored() == []


def test_blank_keyword_detail_is_a_string(client: TestClient) -> None:
    response = client.post("/keyword-mutes", json={"keyword": "   "})

    assert response.json() == {"detail": "Keyword is empty"}


def test_update(client: TestClient) -> None:
    crypto = mute(client, "crypto")
    nft = mute(client, "nft")

    response = client.patch(f"/keyword-mutes/{crypto['id']}", json={"keyword": "bitcoin"})
    assert response.status_code == 200
    assert response.json() == {**crypto, "keyword": "bitcoin"}

    response = client.patch(f"/keyword-mutes/{nft['id']}", json={"keyword": "Bitcoin"})
    assert response.status_code == 409
    assert response.json() == {"detail": "'Bitcoin' is already muted"}

    response = client.patch("/keyword-mutes/999", json={"keyword": "x"})
    assert response.status_code == 404
    assert stored() == ["bitcoin", "nft"]


def test_delete(client: TestClient) -> None:
    crypto = mute(client, "crypto")

    assert client.delete(f"/keyword-mutes/{crypto['id']}").status_code == 204
    assert client.delete(f"/keyword-mutes/{crypto['id']}").status_code == 404
    assert client.delete("/keyword-mutes/0").status_code == 422
    assert stored() == []
