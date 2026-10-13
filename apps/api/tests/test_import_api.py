from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app
from homefeed_core import importer
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory

FIXTURES = Path(__file__).resolve().parents[3] / "packages" / "core" / "tests" / "fixtures"
TAKEOUT = FIXTURES / "takeout"
SPACE = "UCspaceexplained00000001"


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


def upload(client: TestClient, name: str, content: bytes, **form: str):
    return client.post("/import/takeout", files={"file": (name, content)}, data=form)


def count(table: str) -> int:
    with get_session_factory()() as session:
        return session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


@pytest.mark.parametrize("name", ["watch-history.json", "watch-history.html"])
def test_imports_a_watch_history(client: TestClient, name: str) -> None:
    response = upload(client, name, (TAKEOUT / name).read_bytes(), subscribe_min_watches="2")

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["format"] == name.rsplit(".", 1)[1]
    assert report["watches"] == 5
    assert report["removed"] == 2
    assert report["skipped"] == 2
    assert report["malformed"] in (3, 5)
    assert report["new_candidates"] == 4
    assert report["subscribed"] == [SPACE]
    assert count("candidates") == 4
    assert count("channel_prefs") == 1
    assert count("ratings") == 0
    assert count("watch_events") == 0
    assert client.get("/channels").json()[0]["channel_id"] == SPACE


def test_subscribes_to_nothing_by_default(client: TestClient) -> None:
    content = (TAKEOUT / "watch-history.json").read_bytes()
    response = upload(client, "watch-history.json", content, max_candidates="1")

    assert response.status_code == 200, response.text
    assert response.json()["subscribed"] == []
    assert response.json()["new_candidates"] == 1
    assert count("channel_prefs") == 0


def test_rejects_files_that_are_not_a_watch_history(client: TestClient) -> None:
    response = upload(client, "notes.txt", b"hello")

    assert response.status_code == 422
    assert "Not a Takeout watch history" in response.json()["detail"]


def test_rejects_invalid_options(client: TestClient) -> None:
    for form in ({"subscribe_min_watches": "0"}, {"max_candidates": "-1"}):
        response = upload(client, "watch-history.json", b"[]", **form)
        assert response.status_code == 422


def test_rejects_files_that_are_too_large(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(importer, "MAX_TAKEOUT_BYTES", 10)

    response = upload(client, "watch-history.json", b"[" + b" " * 20 + b"]")

    assert response.status_code == 413
    assert count("candidates") == 0
