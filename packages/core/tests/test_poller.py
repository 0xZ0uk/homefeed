import random
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core.candidates import list_candidates
from homefeed_core.curation import subscribe, unsubscribe, update_channel
from homefeed_core.db import open_database
from homefeed_core.gateway import ExtractionError, GatewayError, RateLimitedError
from homefeed_core.gateway.fake import FakeGateway, make_channel
from homefeed_core.poller import (
    FeedParseError,
    PollSchedule,
    due_channel_ids,
    parse_feed,
    poll_due_channels,
)

RSS = Path(__file__).parent / "fixtures" / "rss"
MKBHD = "UCBJycsmduvYEL83R_U4JriQ"  # 15 entries, 3 of them Shorts
JAWED = "UC4QobU6STFB0P71PMvOGN5A"  # a single video
NEWEST_MKBHD = "_0G4OG39XjI"
MKBHD_SHORTS = {"R6yNUnRXZ64", "uJdjKOBikTE", "v-_d2e7x4KA"}

T0 = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
NO_JITTER = PollSchedule(jitter=0.0)


def recorded(channel_id: str) -> bytes:
    return (RSS / f"{channel_id}.xml").read_bytes()


def without_newest_entry(xml: bytes) -> bytes:
    """The feed as it looked before the channel's latest upload."""
    ET.register_namespace("", "http://www.w3.org/2005/Atom")
    ET.register_namespace("yt", "http://www.youtube.com/xml/schemas/2015")
    ET.register_namespace("media", "http://search.yahoo.com/mrss/")
    root = ET.fromstring(xml)
    root.remove(root.findall("{http://www.w3.org/2005/Atom}entry")[0])
    return ET.tostring(root, xml_declaration=True, encoding="UTF-8")


class Feeds:
    """A `FeedFetcher` serving recorded feeds; tests can swap a feed or make it fail."""

    def __init__(self) -> None:
        self.feeds: dict[str, bytes] = {MKBHD: recorded(MKBHD), JAWED: recorded(JAWED)}
        self.failures: dict[str, GatewayError] = {}
        self.calls: list[str] = []

    def __call__(self, channel_id: str) -> bytes:
        self.calls.append(channel_id)
        if channel_id in self.failures:
            raise self.failures[channel_id]
        return self.feeds[channel_id]


class Clock:
    def __init__(self, at: datetime = T0) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def advance(self, delta: timedelta) -> None:
        self.at += delta


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    gateway = FakeGateway()
    with factory.begin() as session:
        for channel_id, title in ((MKBHD, "Marques Brownlee"), (JAWED, "jawed")):
            gateway.add_channel(make_channel(channel_id, title=title))
            subscribe(session, gateway, f"https://www.youtube.com/channel/{channel_id}")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


@pytest.fixture
def feeds() -> Feeds:
    return Feeds()


@pytest.fixture
def clock() -> Clock:
    return Clock()


def poll(
    sessions: sessionmaker[Session],
    feeds: Feeds,
    clock: Clock,
    schedule: PollSchedule = NO_JITTER,
) -> list[str]:
    return poll_due_channels(
        sessions=sessions, fetch=feeds, schedule=schedule, now=clock, rng=random.Random(0)
    )


def poll_state(sessions: sessionmaker[Session], channel_id: str) -> dict[str, object]:
    with sessions() as session:
        row = session.execute(
            text(
                "SELECT next_poll_at, last_polled_at, last_success_at, consecutive_failures, "
                "last_error FROM channel_polls WHERE channel_id = :id"
            ),
            {"id": channel_id},
        ).one()
        return dict(row._mapping)


# Parsing


def test_parse_recorded_feed() -> None:
    feed = parse_feed(recorded(MKBHD))

    assert feed.channel_id == MKBHD
    assert feed.title == "Marques Brownlee"
    assert len(feed.entries) == 15
    newest = feed.entries[0]
    assert newest.video_id == NEWEST_MKBHD
    assert newest.channel_id == MKBHD
    assert newest.title == "WTF is a Googlebook?"
    assert newest.published_at == datetime(2026, 10, 8, 21, 0, 40, tzinfo=UTC)
    assert newest.updated_at == datetime(2026, 10, 11, 15, 8, 32, tzinfo=UTC)
    assert newest.view_count == 6971558
    assert newest.thumbnail_url == "https://i4.ytimg.com/vi/_0G4OG39XjI/hqdefault.jpg"
    assert newest.description is not None
    assert newest.description.startswith("New laptops are dropping")
    assert {entry.video_id for entry in feed.entries if entry.is_short} == MKBHD_SHORTS


def test_parse_single_entry_feed() -> None:
    feed = parse_feed(recorded(JAWED))

    assert feed.channel_id == JAWED
    assert [(e.video_id, e.title, e.is_short) for e in feed.entries] == [
        ("jNQXAC9IVRw", "Me at the zoo", False)
    ]


def test_parse_feed_without_entries() -> None:
    xml = b'<feed xmlns="http://www.w3.org/2005/Atom"><title>Empty</title></feed>'

    assert parse_feed(xml).entries == []


@pytest.mark.parametrize(
    "xml",
    [b"<!DOCTYPE html><html><title>Error 404 (Not Found)!!1</title>", b"", b"<rss></rss>"],
)
def test_parse_rejects_non_feeds(xml: bytes) -> None:
    with pytest.raises(FeedParseError):
        parse_feed(xml)


# Polling


def test_poll_records_videos_and_subscription_candidates(
    sessions: sessionmaker[Session], feeds: Feeds, clock: Clock
) -> None:
    new = poll(sessions, feeds, clock)

    assert sorted(feeds.calls) == sorted([MKBHD, JAWED])
    assert len(new) == 16
    with sessions() as session:
        pool = {c.video_id: c for c in list_candidates(session)}
        video = session.execute(
            text(
                "SELECT channel_id, title, published_at, duration_seconds, is_short, view_count "
                "FROM videos WHERE id = :id"
            ),
            {"id": NEWEST_MKBHD},
        ).one()
        shorts = set(session.execute(text("SELECT id FROM videos WHERE is_short = 1")).scalars())
    assert set(pool) == set(new)
    candidate = pool[NEWEST_MKBHD]
    assert (candidate.source, candidate.source_detail) == ("subscription", MKBHD)
    assert candidate.first_seen_at == "2026-10-12T06:00:00.000Z"
    assert pool["jNQXAC9IVRw"].source_detail == JAWED
    assert tuple(video) == (
        MKBHD,
        "WTF is a Googlebook?",
        "2026-10-08T21:00:40.000Z",
        None,  # RSS has no duration
        0,
        6971558,
    )
    assert shorts == MKBHD_SHORTS


def test_channels_are_not_polled_before_they_are_due(
    sessions: sessionmaker[Session], feeds: Feeds, clock: Clock
) -> None:
    poll(sessions, feeds, clock)
    feeds.calls.clear()

    clock.advance(timedelta(minutes=59))
    assert poll(sessions, feeds, clock) == []
    assert feeds.calls == []

    clock.advance(timedelta(minutes=1))
    poll(sessions, feeds, clock)
    assert sorted(feeds.calls) == sorted([MKBHD, JAWED])


def test_jitter_spreads_the_next_poll_within_bounds(
    sessions: sessionmaker[Session], feeds: Feeds, clock: Clock
) -> None:
    poll(sessions, feeds, clock, schedule=PollSchedule(jitter=0.5))

    for channel_id in (MKBHD, JAWED):
        next_poll = datetime.fromisoformat(str(poll_state(sessions, channel_id)["next_poll_at"]))
        assert T0 + timedelta(hours=1) <= next_poll <= T0 + timedelta(hours=1.5)


def test_repolling_dedupes_and_keeps_first_seen(
    sessions: sessionmaker[Session], feeds: Feeds, clock: Clock
) -> None:
    feeds.feeds[MKBHD] = without_newest_entry(recorded(MKBHD))
    first = poll(sessions, feeds, clock)
    assert NEWEST_MKBHD not in first

    feeds.feeds[MKBHD] = recorded(MKBHD)
    clock.advance(timedelta(hours=2))
    second = poll(sessions, feeds, clock)

    assert second == [NEWEST_MKBHD]
    with sessions() as session:
        pool = {c.video_id: c for c in list_candidates(session)}
        count = session.execute(text("SELECT count(*) FROM candidates")).scalar_one()
    assert count == 16
    assert pool[NEWEST_MKBHD].first_seen_at == "2026-10-12T08:00:00.000Z"
    assert pool["jNQXAC9IVRw"].first_seen_at == "2026-10-12T06:00:00.000Z"


def test_repolling_keeps_metadata_fetched_elsewhere(
    sessions: sessionmaker[Session], feeds: Feeds, clock: Clock
) -> None:
    poll(sessions, feeds, clock)
    with sessions.begin() as session:
        session.execute(
            text(
                "UPDATE videos SET duration_seconds = 900, live_status = 'not_live', "
                "thumbnail_url = 'https://i.ytimg.com/vi/x/maxres.jpg' WHERE id = :id"
            ),
            {"id": NEWEST_MKBHD},
        )

    clock.advance(timedelta(hours=2))
    poll(sessions, feeds, clock)

    with sessions() as session:
        row = session.execute(
            text("SELECT duration_seconds, live_status, thumbnail_url FROM videos WHERE id = :id"),
            {"id": NEWEST_MKBHD},
        ).one()
    assert tuple(row) == (900, "not_live", "https://i.ytimg.com/vi/x/maxres.jpg")


def test_failures_back_off_exponentially_and_reset_on_success(
    sessions: sessionmaker[Session], feeds: Feeds, clock: Clock
) -> None:
    schedule = PollSchedule(
        jitter=0.0, retry_after=timedelta(minutes=15), max_backoff=timedelta(hours=1)
    )
    feeds.failures[MKBHD] = RateLimitedError("HTTP Error 429")

    delays: list[timedelta] = []
    for failures in range(1, 5):
        poll(sessions, feeds, clock, schedule)
        state = poll_state(sessions, MKBHD)
        assert state["consecutive_failures"] == failures
        assert state["last_error"] == "HTTP Error 429"
        assert state["last_success_at"] is None
        next_poll = datetime.fromisoformat(str(state["next_poll_at"]))
        delays.append(next_poll - clock())
        clock.at = next_poll

    assert delays == [
        timedelta(minutes=15),
        timedelta(minutes=30),
        timedelta(hours=1),
        timedelta(hours=1),  # capped
    ]

    del feeds.failures[MKBHD]
    new = poll(sessions, feeds, clock, schedule)

    assert NEWEST_MKBHD in new
    state = poll_state(sessions, MKBHD)
    assert state["consecutive_failures"] == 0
    assert state["last_error"] is None
    assert state["last_success_at"] == state["last_polled_at"]


def test_failing_channel_does_not_block_others(
    sessions: sessionmaker[Session], feeds: Feeds, clock: Clock
) -> None:
    feeds.failures[MKBHD] = ExtractionError("connection reset")

    new = poll(sessions, feeds, clock)

    assert new == ["jNQXAC9IVRw"]
    assert poll_state(sessions, MKBHD)["consecutive_failures"] == 1
    assert poll_state(sessions, JAWED)["consecutive_failures"] == 0


def test_unparseable_feed_backs_off(
    sessions: sessionmaker[Session], feeds: Feeds, clock: Clock
) -> None:
    feeds.feeds[JAWED] = b"<html>sorry</html>"

    poll(sessions, feeds, clock)

    state = poll_state(sessions, JAWED)
    assert state["consecutive_failures"] == 1
    assert "Not an Atom feed" in str(state["last_error"])


def test_muted_and_unsubscribed_channels_are_not_polled(
    sessions: sessionmaker[Session], feeds: Feeds, clock: Clock
) -> None:
    with sessions.begin() as session:
        update_channel(session, MKBHD, muted=True)
        unsubscribe(session, JAWED)

    assert poll(sessions, feeds, clock) == []
    assert feeds.calls == []


def test_channels_muted_for_a_time_are_polled_again_once_it_runs_out(
    sessions: sessionmaker[Session], feeds: Feeds, clock: Clock
) -> None:
    with sessions.begin() as session:
        update_channel(session, MKBHD, mute_days=3, now=T0)

    poll(sessions, feeds, clock)
    assert feeds.calls == [JAWED]

    feeds.calls.clear()
    clock.advance(timedelta(days=2, hours=23))
    poll(sessions, feeds, clock)
    assert MKBHD not in feeds.calls

    clock.advance(timedelta(hours=1))
    poll(sessions, feeds, clock)
    assert MKBHD in feeds.calls


def test_due_channels_most_overdue_first_and_limited(
    sessions: sessionmaker[Session], feeds: Feeds, clock: Clock
) -> None:
    feeds.failures[JAWED] = ExtractionError("boom")
    poll(sessions, feeds, clock)  # JAWED retries after 15 min, MKBHD polls after an hour

    with sessions() as session:
        assert due_channel_ids(session, T0) == []
        assert due_channel_ids(session, T0 + timedelta(hours=2)) == [JAWED, MKBHD]
        assert due_channel_ids(session, T0 + timedelta(hours=2), limit=1) == [JAWED]


def test_entries_from_other_channels_are_ignored(
    sessions: sessionmaker[Session], feeds: Feeds, clock: Clock
) -> None:
    feeds.feeds[JAWED] = recorded(MKBHD)  # wrong feed served for this channel

    new = poll(sessions, feeds, clock)

    with sessions() as session:
        sources = {c.source_detail for c in list_candidates(session)}
    assert sources == {MKBHD}
    assert len(new) == 15
