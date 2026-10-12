from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.candidates import SUBSCRIPTION, Candidate, list_candidates, record
from homefeed_core.db import open_database

CHANNEL = "UC" + "c" * 22
T0 = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
VIDEOS = ["aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc"]


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    with factory.begin() as session:
        session.execute(text("INSERT INTO channels (id, title) VALUES (:id, 'C')"), {"id": CHANNEL})
        session.execute(
            text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :channel, :id)"),
            [{"id": video_id, "channel": CHANNEL} for video_id in VIDEOS],
        )
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def test_record_returns_new_ids_and_dedupes(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        first = record(session, ["aaaaaaaaaaa", "bbbbbbbbbbb", "aaaaaaaaaaa"], source=SUBSCRIPTION)
        second = record(session, ["bbbbbbbbbbb", "ccccccccccc"], source=SUBSCRIPTION)
        empty = record(session, [], source=SUBSCRIPTION)

    assert first == ["aaaaaaaaaaa", "bbbbbbbbbbb"]
    assert second == ["ccccccccccc"]
    assert empty == []
    with sessions() as session:
        assert len(list_candidates(session)) == 3


def test_record_keeps_first_seen_and_attribution(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        record(session, ["aaaaaaaaaaa"], source=SUBSCRIPTION, source_detail=CHANNEL, now=T0)
        record(
            session,
            ["aaaaaaaaaaa"],
            source=SUBSCRIPTION,
            source_detail="other",
            now=T0 + timedelta(days=1),
        )

    with sessions() as session:
        assert list_candidates(session) == [
            Candidate("aaaaaaaaaaa", SUBSCRIPTION, CHANNEL, "2026-10-12T06:00:00.000Z")
        ]


def test_list_dedupes_across_sources_attributing_the_first(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        record(session, ["aaaaaaaaaaa"], source="related", source_detail="xxxxxxxxxxx", now=T0)
        later = T0 + timedelta(hours=1)
        new = record(session, ["aaaaaaaaaaa", "bbbbbbbbbbb"], source=SUBSCRIPTION, now=later)

    assert new == ["bbbbbbbbbbb"]  # already in the pool from another source
    with sessions() as session:
        pool = list_candidates(session)
        from_subscriptions = list_candidates(session, source=SUBSCRIPTION)
        from_related = list_candidates(session, source="related")
    assert [(c.video_id, c.source, c.first_seen_at) for c in pool] == [
        ("bbbbbbbbbbb", SUBSCRIPTION, "2026-10-12T07:00:00.000Z"),
        ("aaaaaaaaaaa", "related", "2026-10-12T06:00:00.000Z"),
    ]
    assert [c.video_id for c in from_subscriptions] == ["bbbbbbbbbbb", "aaaaaaaaaaa"]
    assert [c.video_id for c in from_related] == ["aaaaaaaaaaa"]


def test_list_since(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        for days, video_id in enumerate(VIDEOS):
            record(session, [video_id], source=SUBSCRIPTION, now=T0 + timedelta(days=days))

    with sessions() as session:
        recent = list_candidates(session, since=T0 + timedelta(days=1))
    assert [c.video_id for c in recent] == ["ccccccccccc", "bbbbbbbbbbb"]


def test_candidates_need_a_stored_video(sessions: sessionmaker[Session]) -> None:
    with pytest.raises(IntegrityError), sessions.begin() as session:
        record(session, ["zzzzzzzzzzz"], source=SUBSCRIPTION)


def test_deleting_a_video_removes_its_candidates(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        record(session, VIDEOS, source=SUBSCRIPTION)
        session.execute(text("DELETE FROM videos WHERE id = 'aaaaaaaaaaa'"))

    with sessions() as session:
        assert {c.video_id for c in list_candidates(session)} == {"bbbbbbbbbbb", "ccccccccccc"}
