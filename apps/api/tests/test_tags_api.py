from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.gateway import Video
from homefeed_core.tags import ProposedTag, resolve_tag, set_llm_tags
from homefeed_core.videos import store_video

OLD, MID, NEW, BARE = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"


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


def store(video_id: str, title: str, published: datetime | None) -> None:
    with get_session_factory().begin() as session:
        store_video(
            session,
            Video(
                id=video_id,
                title=title,
                channel_id="UC" + "w" * 22,
                channel_title="Wood Shop",
                duration_seconds=600,
                published_at=published,
                view_count=1234,
            ),
        )


def tag(video_id: str, *labels: str) -> None:
    with get_session_factory().begin() as session:
        set_llm_tags(
            session, video_id, [ProposedTag(label, 0.8) for label in labels], prompt_version=1
        )


@pytest.fixture
def tagged(client: TestClient) -> None:
    store(OLD, "Old plane", datetime(2025, 1, 1, tzinfo=UTC))
    store(NEW, "New plane", datetime(2026, 1, 1, tzinfo=UTC))
    store(MID, "Dovetails", datetime(2025, 6, 1, tzinfo=UTC))
    store(BARE, "No date", None)
    tag(OLD, "woodworking", "hand tools")
    tag(NEW, "woodworking")
    tag(MID, "woodworking", "joinery")
    tag(BARE, "woodworking")


def test_tag_page_lists_videos_newest_published_first(client: TestClient, tagged: None) -> None:
    response = client.get("/tags/woodworking")

    assert response.status_code == 200
    body = response.json()
    assert body["tag"] == {
        "id": body["tag"]["id"],
        "slug": "woodworking",
        "label": "woodworking",
        "video_count": 4,
    }
    assert [video["video_id"] for video in body["videos"]] == [NEW, MID, OLD, BARE]
    assert body["videos"][0] == {
        "video_id": NEW,
        "title": "New plane",
        "duration_seconds": 600,
        "published_at": "2026-01-01T00:00:00.000Z",
        "thumbnail_url": None,
        "view_count": 1234,
        "channel_id": "UC" + "w" * 22,
        "channel_title": "Wood Shop",
        "channel_thumbnail_url": None,
        "watched": False,
    }


def test_tag_page_is_paginated(client: TestClient, tagged: None) -> None:
    page = client.get("/tags/woodworking", params={"limit": 2, "offset": 1}).json()

    assert [video["video_id"] for video in page["videos"]] == [MID, OLD]
    assert page["tag"]["video_count"] == 4  # the total, not the page's size
    assert client.get("/tags/woodworking", params={"offset": 10}).json()["videos"] == []
    assert client.get("/tags/woodworking", params={"limit": 0}).status_code == 422


def test_tag_page_skips_removed_links(client: TestClient, tagged: None) -> None:
    with get_session_factory().begin() as session:
        session.execute(
            text(
                "UPDATE video_tags SET removed_at = '2026-02-01T00:00:00.000Z' "
                "WHERE video_id = :video_id"
            ),
            {"video_id": NEW},
        )

    body = client.get("/tags/woodworking").json()

    assert [video["video_id"] for video in body["videos"]] == [MID, OLD, BARE]
    assert body["tag"]["video_count"] == 3


def test_tag_page_marks_watched_videos(client: TestClient, tagged: None) -> None:
    response = client.post(
        "/watch-events",
        json={"video_id": OLD, "event_type": "play", "position": 0, "duration": 600},
    )
    assert response.status_code == 201
    assert client.put(f"/ratings/{MID}", json={"score": 7}).status_code == 200

    videos = client.get("/tags/woodworking").json()["videos"]

    assert {video["video_id"]: video["watched"] for video in videos} == {
        NEW: False,
        MID: True,
        OLD: True,
        BARE: False,
    }


def test_an_alias_resolves_to_the_canonical_tag(client: TestClient, tagged: None) -> None:
    with get_session_factory().begin() as session:
        resolve_tag(session, "wood-working")  # recorded as an alias of woodworking

    body = client.get("/tags/wood-working").json()

    assert body["tag"]["slug"] == "woodworking"
    assert len(body["videos"]) == 4


def test_unknown_tag_is_404(client: TestClient, tagged: None) -> None:
    response = client.get("/tags/no-such-tag")

    assert response.status_code == 404
    assert response.json() == {"detail": "No such tag"}


def test_a_tag_without_videos_is_an_empty_page(client: TestClient) -> None:
    with get_session_factory().begin() as session:
        resolve_tag(session, "orphan")

    body = client.get("/tags/orphan").json()

    assert body["tag"]["video_count"] == 0
    assert body["videos"] == []


def test_lists_tags_by_video_count(client: TestClient, tagged: None) -> None:
    with get_session_factory().begin() as session:
        resolve_tag(session, "orphan")  # no videos: not listed

    response = client.get("/tags")

    assert response.status_code == 200
    assert [(item["slug"], item["video_count"]) for item in response.json()] == [
        ("woodworking", 4),
        ("hand-tools", 1),
        ("joinery", 1),
    ]
    page = client.get("/tags", params={"limit": 1, "offset": 1}).json()
    assert [item["slug"] for item in page] == ["hand-tools"]


def test_searches_tags(client: TestClient, tagged: None) -> None:
    with get_session_factory().begin() as session:
        resolve_tag(session, "wood-working")  # alias of woodworking

    def slugs(q: str) -> list[str]:
        response = client.get("/tags", params={"q": q})
        assert response.status_code == 200
        return [item["slug"] for item in response.json()]

    assert slugs("Hand T") == ["hand-tools"]
    assert slugs("wood") == ["woodworking"]
    assert slugs("wood-working") == ["woodworking"]  # the alias
    assert slugs("zzz") == []
    assert slugs("  ") == ["woodworking", "hand-tools", "joinery"]
