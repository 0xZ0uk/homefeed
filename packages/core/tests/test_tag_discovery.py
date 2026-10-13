import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.candidates import TAG, Candidate, generate
from homefeed_core.candidates import list_candidates as pool
from homefeed_core.curation import add_topic, subscribe_tag
from homefeed_core.db import open_database
from homefeed_core.embeddings import StubEmbeddingProvider
from homefeed_core.gateway import RateLimitedError
from homefeed_core.gateway.fake import FakeGateway, make_channel, make_video
from homefeed_core.ratings import set_rating
from homefeed_core.tag_discovery import (
    TagDiscoverySource,
    found_today,
    subscribed_tags,
)
from homefeed_core.tags import Tag, resolve_tag
from homefeed_core.user_settings import update_user_settings

T0 = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)
WOOD = make_channel("UC" + "w" * 22, title="Wood", handle="@wood")
METAL = make_channel("UC" + "m" * 22, title="Metal")


@pytest.fixture(autouse=True)
def utc_local_time() -> Iterator[None]:
    """The daily cap counts from local midnight; make that UTC midnight."""
    before = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    yield
    if before is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = before
    time.tzset()


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def make_tag(session: Session, label: str) -> Tag:
    tag = resolve_tag(session, label)
    assert tag is not None
    return tag


def subscribe(sessions: sessionmaker[Session], label: str, weight: float = 0.5) -> int:
    with sessions.begin() as session:
        topic, _ = subscribe_tag(
            session, StubEmbeddingProvider(), make_tag(session, label), weight=weight, now=T0
        )
    return topic.id


def videos(prefix: str, count: int, channel: object = WOOD) -> list:  # type: ignore[type-arg]
    return [make_video(f"{prefix}{i:0>10}", channel=channel) for i in range(count)]  # type: ignore[arg-type]


def discover(
    sessions: sessionmaker[Session], gateway: FakeGateway, *, per_day: int = 10, at: datetime = T0
) -> dict[str, list[str]]:
    source = TagDiscoverySource(sessions, gateway, per_tag_per_day=per_day, now=at)
    report = generate([source], sessions=sessions, now=at)
    assert not report.failed, report.failed
    return report.new


def tagged(sessions: sessionmaker[Session]) -> list[Candidate]:
    with sessions() as session:
        return pool(session, source=TAG)


def test_searches_each_subscribed_tag_and_records_candidates_by_slug(
    sessions: sessionmaker[Session],
) -> None:
    subscribe(sessions, "Woodworking")
    subscribe(sessions, "Blacksmithing")
    gateway = FakeGateway()
    gateway.add_search("Woodworking", videos("w", 3))
    gateway.add_search("Blacksmithing", videos("b", 2, METAL))

    new = discover(sessions, gateway)

    assert sorted(query for query, _ in gateway.searches) == ["Blacksmithing", "Woodworking"]
    assert len(new[TAG]) == 5
    found = {(c.source, c.source_detail) for c in tagged(sessions)}
    assert found == {(TAG, "woodworking"), (TAG, "blacksmithing")}


def test_only_tags_with_positive_effective_weight_are_searched(
    sessions: sessionmaker[Session],
) -> None:
    subscribe(sessions, "Muted tag", weight=-0.5)
    subscribe(sessions, "Zero tag", weight=0)
    with sessions.begin() as session:
        add_topic(
            session, StubEmbeddingProvider(), name="Plain topic", description="plain", weight=1
        )  # no tag
    subscribe(sessions, "Wanted")
    gateway = FakeGateway()

    discover(sessions, gateway)

    with sessions() as session:
        assert [t.slug for t in subscribed_tags(session, now=T0)] == ["wanted"]
    assert [query for query, _ in gateway.searches] == ["Wanted"]


def test_each_tag_is_searched_once_a_day(sessions: sessionmaker[Session]) -> None:
    subscribe(sessions, "Woodworking")
    gateway = FakeGateway()
    gateway.add_search("Woodworking", videos("w", 3))

    discover(sessions, gateway)
    discover(sessions, gateway, at=T0 + timedelta(hours=6))
    assert len(gateway.searches) == 1

    discover(sessions, gateway, at=T0 + timedelta(hours=23))  # within the grace of a day
    assert len(gateway.searches) == 2


def test_cap_per_tag_holds_across_runs_on_the_same_day(sessions: sessionmaker[Session]) -> None:
    subscribe(sessions, "Woodworking")
    gateway = FakeGateway()
    gateway.add_search("Woodworking", videos("w", 12))

    first = discover(sessions, gateway, per_day=5)
    with sessions.begin() as session:
        session.execute(text("DELETE FROM tag_discovery_runs"))  # due again, the same day
    second = discover(sessions, gateway, per_day=7, at=T0 + timedelta(hours=1))
    with sessions.begin() as session:
        session.execute(text("DELETE FROM tag_discovery_runs"))
    third = discover(sessions, gateway, per_day=7, at=T0 + timedelta(hours=2))

    assert (len(first[TAG]), len(second[TAG]), len(third[TAG])) == (5, 2, 0)
    assert len(gateway.searches) == 2  # nothing left under the cap: no search at all
    with sessions() as session:
        assert found_today(session, "woodworking", now=T0) == 7


def test_the_cap_is_the_user_setting_unless_given(sessions: sessionmaker[Session]) -> None:
    subscribe(sessions, "Woodworking")
    gateway = FakeGateway()
    gateway.add_search("Woodworking", videos("w", 12))
    with sessions.begin() as session:
        update_user_settings(session, {"tag_discovery_per_day": 3})

    source = TagDiscoverySource(sessions, gateway, now=T0)
    new = generate([source], sessions=sessions, now=T0).new

    assert len(new[TAG]) == 3


def test_the_day_is_the_user_time_zone_day(sessions: sessionmaker[Session]) -> None:
    subscribe(sessions, "Woodworking")
    gateway = FakeGateway()
    gateway.add_search("Woodworking", videos("w", 12))
    discover(sessions, gateway, per_day=4)  # 12:00 UTC
    with sessions.begin() as session:
        update_user_settings(session, {"timezone": "Asia/Tokyo"})
        session.execute(text("DELETE FROM tag_discovery_runs"))

    # 16:00 UTC is 01:00 the next day in Tokyo: a new day, a new cap.
    source = TagDiscoverySource(sessions, gateway, per_tag_per_day=4, now=T0 + timedelta(hours=4))
    new = generate([source], sessions=sessions, now=T0 + timedelta(hours=4)).new

    assert len(new[TAG]) == 4


def test_the_cap_starts_over_the_next_day(sessions: sessionmaker[Session]) -> None:
    subscribe(sessions, "Woodworking")
    gateway = FakeGateway()
    gateway.add_search("Woodworking", videos("w", 12))

    discover(sessions, gateway, per_day=4)
    tomorrow = discover(sessions, gateway, per_day=4, at=T0 + timedelta(days=1))

    assert len(tomorrow[TAG]) == 4
    assert len(tagged(sessions)) == 8


def test_known_and_rated_videos_are_not_new(sessions: sessionmaker[Session]) -> None:
    subscribe(sessions, "Woodworking")
    found = videos("w", 4)
    gateway = FakeGateway()
    gateway.add_search("Woodworking", found)
    discover(sessions, gateway, per_day=2)  # takes w0, w1
    with sessions.begin() as session:
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, 'Wood') ON CONFLICT DO NOTHING"),
            {"id": WOOD.id},
        )
        session.execute(
            text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :channel, 'x')"),
            {"id": found[2].id, "channel": WOOD.id},
        )
        set_rating(session, found[2].id, 9)

    new = discover(sessions, gateway, per_day=10, at=T0 + timedelta(days=1))

    assert new[TAG] == [found[3].id]


def test_videos_of_muted_channels_are_skipped(sessions: sessionmaker[Session]) -> None:
    subscribe(sessions, "Woodworking")
    with sessions.begin() as session:
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, 'Metal')"), METAL.__dict__ | {}
        )
        session.execute(
            text("INSERT INTO channel_prefs (channel_id, muted) VALUES (:id, 1)"), {"id": METAL.id}
        )
    gateway = FakeGateway()
    gateway.add_search("Woodworking", [*videos("m", 2, METAL), *videos("w", 2)])

    new = discover(sessions, gateway, per_day=3)

    assert new[TAG] == ["w0000000000", "w0000000001"]


def test_a_video_found_by_two_tags_is_recorded_for_the_first(
    sessions: sessionmaker[Session],
) -> None:
    subscribe(sessions, "Woodworking")
    subscribe(sessions, "Joinery")
    shared = videos("s", 1)
    gateway = FakeGateway()
    gateway.add_search("Woodworking", shared)
    gateway.add_search("Joinery", shared)

    new = discover(sessions, gateway)

    assert new[TAG] == [shared[0].id]
    with sessions() as session:
        assert (
            found_today(session, "woodworking", now=T0) + found_today(session, "joinery", now=T0)
            == 1
        )


def test_a_failing_tag_is_recorded_and_the_others_still_run(
    sessions: sessionmaker[Session],
) -> None:
    subscribe(sessions, "Woodworking")
    subscribe(sessions, "Blacksmithing")
    gateway = FakeGateway()
    gateway.add_search("Blacksmithing", videos("b", 2, METAL))
    gateway.fail("search", "Woodworking", RateLimitedError("slow down"))

    new = discover(sessions, gateway)

    assert len(new[TAG]) == 2
    with sessions() as session:
        runs = {
            slug: (error, found)
            for slug, error, found in session.execute(
                text(
                    "SELECT t.slug, r.last_error, r.last_found_count FROM tag_discovery_runs r "
                    "JOIN tags t ON t.id = r.tag_id"
                )
            )
        }
    assert runs == {"woodworking": ("slow down", None), "blacksmithing": (None, 2)}


def test_the_source_fails_only_if_every_search_did(sessions: sessionmaker[Session]) -> None:
    subscribe(sessions, "Woodworking")
    gateway = FakeGateway()
    gateway.fail("search", "Woodworking", RateLimitedError("slow down"))
    source = TagDiscoverySource(sessions, gateway, now=T0)

    report = generate([source], sessions=sessions, now=T0)

    assert report.failed == {TAG: "slow down"}
    assert tagged(sessions) == []


def test_without_subscribed_tags_nothing_is_searched(sessions: sessionmaker[Session]) -> None:
    gateway = FakeGateway()

    assert discover(sessions, gateway) == {TAG: []}
    assert gateway.searches == []


def test_a_zero_cap_turns_discovery_off(sessions: sessionmaker[Session]) -> None:
    subscribe(sessions, "Woodworking")
    gateway = FakeGateway()

    discover(sessions, gateway, per_day=0)

    assert gateway.searches == []
