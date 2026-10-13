import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import (
    curation,
    external_sources,
    playlists,
    queue,
    ranking_models,
    saved_searches,
)
from homefeed_core.config import get_settings
from homefeed_core.db import open_database
from homefeed_core.embeddings import StubEmbeddingProvider
from homefeed_core.exporter import EXPORT_FORMAT, SECTIONS, ExportSection, export_data
from homefeed_core.gateway import SearchFilters
from homefeed_core.ratings import set_rating
from homefeed_core.watch_events import record_watch_event

CHANNEL = "UCspaceexplained00000001"
VIDEO = "dQw4w9WgXcQ"
NOW = datetime(2026, 10, 13, 9, 30, tzinfo=UTC)


@pytest.fixture
def sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[sessionmaker[Session]]:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-secret")
    monkeypatch.setenv("FEED_SIZE", "12")
    get_settings.cache_clear()
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()
    get_settings.cache_clear()


def seed(session: Session) -> None:
    session.execute(
        text("INSERT INTO channels (id, title, handle) VALUES (:id, 'Space Explained', '@space')"),
        {"id": CHANNEL},
    )
    session.execute(
        text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :channel, 'Black holes')"),
        {"id": VIDEO, "channel": CHANNEL},
    )
    session.execute(
        text("INSERT INTO channel_prefs (channel_id, prior, pinned) VALUES (:id, 'love', 1)"),
        {"id": CHANNEL},
    )
    set_rating(session, VIDEO, 8.1)
    set_rating(session, "zzzzzzzzzzz", 1.6)  # rated before its metadata was stored
    curation.add_keyword_mute(session, "crypto")
    curation.add_topic(
        session, StubEmbeddingProvider(), name="Woodworking", description="Joinery", weight=0.5
    )
    saved_searches.add_saved_search(session, "lathe", SearchFilters(sort="upload_date"))
    external_sources.add_source(session, "subreddit", "r/videos")
    record_watch_event(session, VIDEO, "play", 0.0, 600.0)
    feed_id = session.execute(
        text("INSERT INTO feeds (date, model_version) VALUES ('2026-10-13', NULL) RETURNING id")
    ).scalar_one()
    session.execute(
        text(
            """
            INSERT INTO feed_items (feed_id, video_id, position, source, score, breakdown,
                                    explanation, is_exploration, dismissed_at, dismiss_reason)
            VALUES (:feed, :video, 0, 'subscription', 0.8, '{"channel": 0.8, "final": 0.8}',
                    'Channel you love', 1, '2026-10-13T10:00:00.000Z', 'not now')
            """
        ),
        {"feed": feed_id, "video": VIDEO},
    )
    ranking_models.record_version(
        session, path="models/1.joblib", kind="ridge", spearman=0.4, mae=0.2, metrics={"n": 40}
    )
    session.execute(text("""INSERT INTO settings (key, value) VALUES ('theme', '"dark"')"""))


def test_exports_every_area(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        seed(session)
        queue.add_to_queue(session, "zzzzzzzzzzz")
        queue.add_to_queue(session, VIDEO, position=0)
        playlist = playlists.create_playlist(session, "Space", "Long watches")
        playlists.add_item(session, playlist.id, VIDEO)
    with sessions.begin() as session:
        data = export_data(session, now=NOW)

    assert data["format"] == EXPORT_FORMAT
    assert data["version"] == 1
    assert data["exported_at"] == "2026-10-13T09:30:00.000Z"
    assert isinstance(data["schema_version"], int)

    ratings = {rating["video_id"]: rating for rating in data["ratings"]}
    assert ratings[VIDEO]["score"] == 8.1
    assert ratings[VIDEO]["title"] == "Black holes"
    assert ratings[VIDEO]["channel_title"] == "Space Explained"
    assert ratings["zzzzzzzzzzz"]["score"] == 1.6
    assert ratings["zzzzzzzzzzz"]["title"] is None

    curation_ = data["curation"]
    [channel] = curation_["channels"]
    assert channel["channel_id"] == CHANNEL
    assert channel["prior"] == "love"
    assert channel["pinned"] is True
    assert [topic["name"] for topic in curation_["topics"]] == ["Woodworking"]
    assert "embedding" not in curation_["topics"][0]
    assert [mute["keyword"] for mute in curation_["keyword_mutes"]] == ["crypto"]
    [search] = curation_["saved_searches"]
    assert search["query"] == "lathe"
    assert search["filters"]["sort"] == "upload_date"
    assert [source["url"] for source in curation_["external_sources"]] == [
        "https://www.reddit.com/r/videos"
    ]

    [feed] = data["feeds"]
    assert feed["date"] == "2026-10-13"
    [item] = feed["items"]
    assert item["video_id"] == VIDEO
    assert item["title"] == "Black holes"
    assert item["breakdown"] == {"channel": 0.8, "final": 0.8}
    assert item["is_exploration"] is True
    assert item["is_pinned"] is False
    assert item["dismiss_reason"] == "not now"

    [event] = data["library"]["watch_events"]
    assert event["video_id"] == VIDEO
    assert event["event_type"] == "play"
    assert event["title"] == "Black holes"
    assert [(q["video_id"], q["position"]) for q in data["library"]["queue"]] == [
        (VIDEO, 0),
        ("zzzzzzzzzzz", 1),
    ]
    [exported_playlist] = data["library"]["playlists"]
    assert exported_playlist["name"] == "Space"
    assert [i["title"] for i in exported_playlist["items"]] == ["Black holes"]

    [model] = data["models"]
    assert model["metrics"] == {"n": 40}

    assert data["settings"]["stored"] == {"theme": "dark"}
    config = data["settings"]["config"]
    assert config["feed_size"] == 12
    assert "openrouter_api_key" not in config
    assert "database_path" not in config
    assert "data_dir" not in config

    json.dumps(data)  # serializable as is


def test_empty_database_exports_empty_sections(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        data = export_data(session)

    assert data["ratings"] == []
    assert data["feeds"] == []
    assert data["library"] == {"watch_events": [], "queue": [], "playlists": []}
    assert data["settings"]["stored"] == {}
    assert all(value == [] for value in data["curation"].values())
    assert "sk-secret" not in json.dumps(data)


def test_sections_registry_controls_the_shape(sessions: sessionmaker[Session]) -> None:
    extra = ExportSection(("library", "extra"), lambda _session: ["more"])
    with sessions.begin() as session:
        data = export_data(session, sections=[*SECTIONS, extra])

    assert data["library"]["extra"] == ["more"]
