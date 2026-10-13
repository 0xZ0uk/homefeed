from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from homefeed_api.main import app
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory

VIDEO = "dQw4w9WgXcQ"


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


def test_export_downloads_all_areas(client: TestClient) -> None:
    assert client.put(f"/ratings/{VIDEO}", json={"grade": "B+"}).status_code == 200
    assert client.post("/keyword-mutes", json={"keyword": "crypto"}).status_code == 201
    watch = {"video_id": VIDEO, "event_type": "play", "position": 0, "duration": 300}
    assert client.post("/watch-events", json=watch).status_code == 201

    response = client.get("/export")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/json")
    disposition = response.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="homefeed-export-')
    assert disposition.endswith('.json"')
    data = response.json()
    assert data["format"] == "homefeed-export"
    assert {"ratings", "curation", "feeds", "library", "settings"} <= data.keys()
    assert [(r["video_id"], r["grade"]) for r in data["ratings"]] == [(VIDEO, "B+")]
    assert [m["keyword"] for m in data["curation"]["keyword_mutes"]] == ["crypto"]
    assert [e["event_type"] for e in data["library"]["watch_events"]] == ["play"]
    assert data["feeds"] == []
    assert data["settings"]["stored"] == {}


def test_export_is_in_the_openapi_schema(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/export"]["get"]
    assert operation["operationId"] == "export_all"
