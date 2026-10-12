from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import feeds
from homefeed_core.candidates import (
    RELATED,
    SUBSCRIPTION,
    Candidate,
    FoundVideo,
    RelatedVideosSource,
    generate,
    list_candidates,
    record,
    top_tier_video_ids,
)
from homefeed_core.config import Settings
from homefeed_core.db import open_database
from homefeed_core.gateway import ExtractionError, RateLimitedError, UnavailableError
from homefeed_core.gateway.fake import FakeGateway, make_channel, make_video
from homefeed_core.grades import Grade
from homefeed_core.ratings import set_rating

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


# Sources


class FakeSource:
    def __init__(self, name: str, found: list[FoundVideo] | Exception) -> None:
        self.name = name
        self.found = found
        self.fetches = 0

    def fetch(self) -> list[FoundVideo]:
        self.fetches += 1
        if isinstance(self.found, Exception):
            raise self.found
        return self.found


OTHER = "UC" + "o" * 22


def found(video_id: str, detail: str | None = None, **fields: Any) -> FoundVideo:
    defaults: dict[str, Any] = {
        "title": f"Video {video_id}",
        "channel_id": OTHER,
        "channel_title": "Other",
        "source_detail": detail,
    }
    return FoundVideo(video_id=video_id, **(defaults | fields))


def test_generate_stores_and_records_what_sources_found(sessions: sessionmaker[Session]) -> None:
    source = FakeSource(
        "search",
        [
            found("ddddddddddd", "woodworking", duration_seconds=600, channel_handle="@other"),
            found("aaaaaaaaaaa", "woodworking", title="Renamed"),  # already stored
        ],
    )

    report = generate([source], sessions=sessions, now=T0)

    assert report.new == {"search": ["ddddddddddd", "aaaaaaaaaaa"]}
    assert report.failed == {}
    with sessions() as session:
        assert {(c.video_id, c.source, c.source_detail) for c in list_candidates(session)} == {
            ("ddddddddddd", "search", "woodworking"),
            ("aaaaaaaaaaa", "search", "woodworking"),
        }
        stored = session.execute(
            text(
                "SELECT v.id, v.title, v.duration_seconds, c.title, c.handle "
                "FROM videos v JOIN channels c ON c.id = v.channel_id "
                "WHERE v.id IN ('aaaaaaaaaaa', 'ddddddddddd') ORDER BY v.id"
            )
        ).all()
    assert [tuple(row) for row in stored] == [
        ("aaaaaaaaaaa", "aaaaaaaaaaa", None, "C", None),  # stored metadata is kept
        ("ddddddddddd", "Video ddddddddddd", 600, "Other", "@other"),
    ]


def test_a_failing_source_does_not_fail_the_run(sessions: sessionmaker[Session]) -> None:
    broken = FakeSource("broken", RuntimeError("boom"))
    throttled = FakeSource("throttled", RateLimitedError("HTTP Error 429"))
    working = FakeSource("working", [found("ddddddddddd")])
    # Results that can't be stored (no channel title) fail only their own source.
    unstorable = FakeSource("unstorable", [found("eeeeeeeeeee", channel_title=None)])

    report = generate([broken, throttled, unstorable, working], sessions=sessions)

    assert report.new == {"working": ["ddddddddddd"]}
    assert report.failed == {
        "broken": "boom",
        "throttled": "HTTP Error 429",
        "unstorable": report.failed["unstorable"],
    }
    assert all(s.fetches == 1 for s in (broken, throttled, unstorable, working))
    with sessions() as session:
        assert [c.video_id for c in list_candidates(session)] == ["ddddddddddd"]
        # The failed source's transaction was rolled back: nothing of it is left.
        assert session.execute(text("SELECT id FROM videos WHERE id = 'eeeeeeeeeee'")).all() == []


def test_a_video_found_through_two_details_is_attributed_to_the_first(
    sessions: sessionmaker[Session],
) -> None:
    source = FakeSource(
        RELATED,
        [found("ddddddddddd", "aaaaaaaaaaa"), found("ddddddddddd", "bbbbbbbbbbb")],
    )

    assert generate([source], sessions=sessions).new == {RELATED: ["ddddddddddd"]}
    with sessions() as session:
        [candidate] = list_candidates(session)
    assert (candidate.source, candidate.source_detail) == (RELATED, "aaaaaaaaaaa")


# Related videos

SEED_CHANNEL = make_channel(CHANNEL, title="C")
RELATED_CHANNEL = make_channel(OTHER, title="Other", handle="@other")


def rate(sessions: sessionmaker[Session], ratings: dict[str, Grade]) -> None:
    with sessions.begin() as session:
        for video_id, grade in ratings.items():
            set_rating(session, video_id, grade)
            # Ratings made one after another, in order.
            session.execute(
                text("UPDATE ratings SET rated_at = :at WHERE video_id = :id"),
                {"id": video_id, "at": f"2026-10-0{len(ratings) - list(ratings).index(video_id)}"},
            )


def related_gateway(related: dict[str, list[str]]) -> FakeGateway:
    gateway = FakeGateway()
    gateway.add_channel(SEED_CHANNEL, [make_video(v, channel=SEED_CHANNEL) for v in VIDEOS])
    for seed, video_ids in related.items():
        gateway.add_related(
            seed,
            [make_video(v, channel=RELATED_CHANNEL, duration_seconds=900) for v in video_ids],
        )
    return gateway


def test_top_tier_seeds_use_the_grade_scale(sessions: sessionmaker[Session]) -> None:
    rate(
        sessions,
        {"aaaaaaaaaaa": "A--", "bbbbbbbbbbb": "B++", "ccccccccccc": "S++", "zzzzzzzzzzz": "A"},
    )

    with sessions() as session:
        # Most recently rated first (the order above); B++ is just below the top tier.
        assert top_tier_video_ids(session) == ["aaaaaaaaaaa", "ccccccccccc", "zzzzzzzzzzz"]
        assert top_tier_video_ids(session, limit=1) == ["aaaaaaaaaaa"]


def test_related_videos_of_top_tier_ratings_are_attributed_to_their_seed(
    sessions: sessionmaker[Session],
) -> None:
    rate(sessions, {"aaaaaaaaaaa": "A+", "bbbbbbbbbbb": "C", "ccccccccccc": "S"})
    gateway = related_gateway(
        {
            "aaaaaaaaaaa": ["ddddddddddd", "eeeeeeeeeee", "ccccccccccc"],  # c is rated
            "bbbbbbbbbbb": ["fffffffffff"],  # not top tier
            "ccccccccccc": ["eeeeeeeeeee", "ggggggggggg", "hhhhhhhhhhh"],
        }
    )
    source = RelatedVideosSource(sessions, gateway, per_seed=2)

    report = generate([source], sessions=sessions, now=T0)

    assert [call for call in gateway.calls if call[0] == "get_related"] == [
        ("get_related", "aaaaaaaaaaa"),
        ("get_related", "ccccccccccc"),
    ]
    assert report.new == {RELATED: ["ddddddddddd", "eeeeeeeeeee", "ggggggggggg"]}
    with sessions() as session:
        pool = list_candidates(session, source=RELATED)
        stored = session.execute(
            text("SELECT channel_id, duration_seconds FROM videos WHERE id = 'ddddddddddd'")
        ).one()
    assert sorted((c.video_id, c.source_detail) for c in pool) == [
        ("ddddddddddd", "aaaaaaaaaaa"),
        ("eeeeeeeeeee", "aaaaaaaaaaa"),  # related to both; the latest seed comes first
        ("ggggggggggg", "ccccccccccc"),
    ]
    assert tuple(stored) == (OTHER, 900)


def test_related_source_skips_failing_seeds(sessions: sessionmaker[Session]) -> None:
    rate(sessions, {"aaaaaaaaaaa": "A", "bbbbbbbbbbb": "A"})
    gateway = related_gateway({"aaaaaaaaaaa": ["ddddddddddd"], "bbbbbbbbbbb": ["eeeeeeeeeee"]})
    gateway.fail("get_related", "aaaaaaaaaaa", UnavailableError("removed"))

    found = RelatedVideosSource(sessions, gateway).fetch()

    assert [(f.video_id, f.source_detail) for f in found] == [("eeeeeeeeeee", "bbbbbbbbbbb")]


def test_related_source_fails_when_every_seed_fails(sessions: sessionmaker[Session]) -> None:
    rate(sessions, {"aaaaaaaaaaa": "A", "bbbbbbbbbbb": "A"})
    gateway = related_gateway({"aaaaaaaaaaa": ["ddddddddddd"], "bbbbbbbbbbb": ["eeeeeeeeeee"]})
    for seed in ("aaaaaaaaaaa", "bbbbbbbbbbb"):
        gateway.fail("get_related", seed, ExtractionError("blocked"))
    working = FakeSource("working", [found("fffffffffff")])

    report = generate([RelatedVideosSource(sessions, gateway), working], sessions=sessions)

    assert report.failed == {RELATED: "blocked"}
    assert report.new == {"working": ["fffffffffff"]}


def test_related_source_without_top_tier_ratings_finds_nothing(
    sessions: sessionmaker[Session],
) -> None:
    rate(sessions, {"aaaaaaaaaaa": "B"})
    gateway = related_gateway({"aaaaaaaaaaa": ["ddddddddddd"]})

    assert RelatedVideosSource(sessions, gateway).fetch() == []
    assert gateway.calls == []


def test_feed_items_keep_the_related_seed(sessions: sessionmaker[Session]) -> None:
    rate(sessions, {"aaaaaaaaaaa": "A+"})
    gateway = related_gateway({"aaaaaaaaaaa": ["ddddddddddd"]})
    now = datetime.now(UTC)
    generate([RelatedVideosSource(sessions, gateway)], sessions=sessions, now=now)

    with sessions.begin() as session:
        feed = feeds.build_feed(session, settings=Settings(), now=now)

    [item] = [item for item in feed.items if item.video_id == "ddddddddddd"]
    assert (item.source, item.source_detail) == (RELATED, "aaaaaaaaaaa")
