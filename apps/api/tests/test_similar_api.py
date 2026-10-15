"""`GET /videos/{id}/similar`: the watch page's "Find more like this"."""

import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from homefeed_api.main import app
from homefeed_core.candidates import RELATED, record
from homefeed_core.config import get_settings
from homefeed_core.db import get_session_factory
from homefeed_core.embeddings import EMBEDDING_DIMENSIONS, store_embedding
from homefeed_core.gateway import Video
from homefeed_core.gateway.fake import make_channel
from homefeed_core.videos import store_video

SEED = "seed0000000"
CLOSE = "close000000"
MIDDLE = "middle00000"
RELATED_VIDEO = "related0000"
WATCHED = "watched0000"
CHANNEL = make_channel("UC" + "w" * 22, title="Woodworking", handle="@wood")


def vector(similarity: float) -> tuple[float, ...]:
    """A unit vector whose cosine similarity to `vector(1.0)` is `similarity`."""
    values = [0.0] * EMBEDDING_DIMENSIONS
    values[0] = similarity
    values[1] = math.sqrt(1 - similarity**2)
    return tuple(values)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "homefeed.sqlite"))
    monkeypatch.setenv("SIMILARITY_FLOOR", "0.3")
    get_settings.cache_clear()
    get_session_factory.cache_clear()
    with TestClient(app) as client:
        yield client
    get_session_factory().kw["bind"].dispose()
    get_settings.cache_clear()
    get_session_factory.cache_clear()


def store(video_id: str, similarity: float | None = None, **fields: Any) -> None:
    with get_session_factory().begin() as session:
        store_video(
            session,
            Video(
                id=video_id,
                title=fields.pop("title", f"Video {video_id}"),
                channel_id=CHANNEL.id,
                channel_title=CHANNEL.title,
                duration_seconds=600,
                view_count=4200,
                thumbnail_url=f"https://example.invalid/{video_id}.jpg",
                **fields,
            ),
        )
        if similarity is not None:
            store_embedding(session, video_id, vector(similarity))


def ids(response: Any) -> list[str]:
    assert response.status_code == 200
    return [video["video_id"] for video in response.json()]


@pytest.fixture
def library(client: TestClient) -> None:
    store(SEED, 1.0, title="Planing a board")
    store(MIDDLE, 0.6)
    store(CLOSE, 0.9, title="Planing, again")
    store(WATCHED, 0.95)
    store(RELATED_VIDEO)
    with get_session_factory().begin() as session:
        session.execute(
            text("UPDATE channels SET thumbnail_url = 'https://example.invalid/wood.jpg'")
        )
        record(session, [RELATED_VIDEO], source=RELATED, source_detail=SEED)
    assert (
        client.post(
            "/watch-events",
            json={"video_id": WATCHED, "event_type": "play", "position": 0, "duration": 600},
        ).status_code
        == 201
    )


@pytest.mark.usefixtures("library")
def test_lists_the_videos_like_this_one_as_cards(client: TestClient) -> None:
    response = client.get(f"/videos/{SEED}/similar")

    assert ids(response) == [CLOSE, MIDDLE, RELATED_VIDEO]  # the watched one is left out
    close, middle, related = response.json()
    assert close == {
        "video_id": CLOSE,
        "title": "Planing, again",
        "duration_seconds": 600,
        "published_at": None,
        "thumbnail_url": f"https://example.invalid/{CLOSE}.jpg",
        "view_count": 4200,
        "channel_id": CHANNEL.id,
        "channel_title": "Woodworking",
        "channel_thumbnail_url": "https://example.invalid/wood.jpg",
        "watched": False,
        "reason": "Similar to this video",
    }
    assert middle["reason"] == "Similar to this video"
    assert related["reason"] == "Related on YouTube"


@pytest.mark.usefixtures("library")
def test_limits_the_list(client: TestClient) -> None:
    assert ids(client.get(f"/videos/{SEED}/similar", params={"limit": 2})) == [CLOSE, MIDDLE]
    assert ids(client.get(f"/videos/{SEED}/similar", params={"limit": 1})) == [CLOSE]


@pytest.mark.usefixtures("library")
@pytest.mark.parametrize("limit", [0, 25, -1])
def test_rejects_a_limit_out_of_range(client: TestClient, limit: int) -> None:
    assert client.get(f"/videos/{SEED}/similar", params={"limit": limit}).status_code == 422


def test_is_empty_until_videos_are_analysed(client: TestClient) -> None:
    store(SEED)  # stored, but not embedded
    store(MIDDLE, 0.6)

    assert client.get(f"/videos/{SEED}/similar").json() == []


def test_unknown_videos_are_a_404(client: TestClient) -> None:
    assert client.get(f"/videos/{SEED}/similar").status_code == 404
    assert client.get("/videos/short/similar").status_code == 422
