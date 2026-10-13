from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import curation
from homefeed_core.candidates import CHANNEL_GRAPH, generate, list_candidates
from homefeed_core.channel_graph import (
    ChannelGraphSource,
    ChannelRef,
    featured_channels,
    liked_channel_ids,
    refresh,
    stale_channel_ids,
    stored_featured,
    suggest,
    suggested_channels,
)
from homefeed_core.db import open_database
from homefeed_core.gateway import Channel, ExtractionError, RateLimitedError, UnavailableError
from homefeed_core.gateway.fake import FakeGateway, make_channel, make_video
from homefeed_core.ratings import set_rating

T0 = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)


def cid(letter: str) -> str:
    return "UC" + letter * 22


LOVED = make_channel(cid("a"), title="Loved", handle="@loved")
LIKED = make_channel(cid("b"), title="Liked")
NEUTRAL = make_channel(cid("c"), title="Neutral")
RATED = make_channel(cid("d"), title="Rated")  # not subscribed; a video rated top tier
MUTED = make_channel(cid("m"), title="Muted")
X = make_channel(cid("x"), title="Xylo", thumbnail_url="https://yt3.example/x.jpg")
Y = make_channel(cid("y"), title="Yew")
Z = make_channel(cid("z"), title="Zinc")
W = make_channel(cid("w"), title="Wren")
V = make_channel(cid("v"), title="Vole")


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


@pytest.fixture
def gateway() -> FakeGateway:
    gateway = FakeGateway()
    for channel in (LOVED, LIKED, NEUTRAL, RATED, MUTED, W, V):
        gateway.add_channel(channel)
    for channel, videos in ((X, "x"), (Y, "y"), (Z, "z")):
        gateway.add_channel(
            channel, [make_video(f"{videos}{i}" + videos * 9, channel=channel) for i in range(4)]
        )
    gateway.add_featured(LOVED.id, [X, Y, NEUTRAL], subscriber_count=1000)
    gateway.add_featured(LIKED.id, [Y, Z])
    gateway.add_featured(NEUTRAL.id, [W])
    gateway.add_featured(MUTED.id, [V])
    gateway.add_featured(RATED.id, [Z, LOVED])
    return gateway


def subscribe(
    sessions: sessionmaker[Session],
    gateway: FakeGateway,
    channel: Channel,
    prior: curation.Prior = "neutral",
    *,
    muted: bool = False,
) -> None:
    with sessions.begin() as session:
        curation.subscribe(session, gateway, f"https://www.youtube.com/channel/{channel.id}")
        curation.update_channel(session, channel.id, prior=prior, muted=muted)


def rate(sessions: sessionmaker[Session], video_id: str, channel: Channel, score: float) -> None:
    with sessions.begin() as session:
        session.execute(
            text("INSERT OR IGNORE INTO channels (id, title) VALUES (:id, :title)"),
            {"id": channel.id, "title": channel.title},
        )
        session.execute(
            text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :channel, :id)"),
            {"id": video_id, "channel": channel.id},
        )
        set_rating(session, video_id, score)


@pytest.fixture
def curated(sessions: sessionmaker[Session], gateway: FakeGateway) -> None:
    subscribe(sessions, gateway, LIKED, "like")
    subscribe(sessions, gateway, LOVED, "love")
    subscribe(sessions, gateway, NEUTRAL)
    subscribe(sessions, gateway, MUTED, "love", muted=True)
    rate(sessions, "ddddddddddd", RATED, 7.8)
    rate(sessions, "eeeeeeeeeee", RATED, 4.7)
    rate(sessions, "mmmmmmmmmmm", MUTED, 9.4)


def test_liked_channels_are_loved_liked_then_top_tier_rated_never_muted(
    sessions: sessionmaker[Session], curated: None
) -> None:
    with sessions() as session:
        assert liked_channel_ids(session) == [LOVED.id, LIKED.id, RATED.id]
        assert liked_channel_ids(session, limit=2) == [LOVED.id, LIKED.id]


def test_a_channel_rated_below_top_tier_is_not_liked(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    rate(sessions, "ddddddddddd", RATED, 6.9)
    subscribe(sessions, gateway, NEUTRAL)

    with sessions() as session:
        assert liked_channel_ids(session) == []


def test_refresh_stores_featured_channels_and_skips_fresh_ones(
    sessions: sessionmaker[Session], gateway: FakeGateway, curated: None
) -> None:
    report = refresh(sessions, gateway, [LOVED.id, LIKED.id], now=T0)
    again = refresh(sessions, gateway, [LOVED.id, LIKED.id], now=T0 + timedelta(days=6))

    assert report.refreshed == [LOVED.id, LIKED.id]
    assert again.refreshed == []
    with sessions() as session:
        stored = stored_featured(session, LOVED.id)
        assert stored_featured(session, NEUTRAL.id) is None
        title = session.execute(text("SELECT title FROM channels WHERE id = :id"), {"id": X.id})
        assert title.scalar_one() == "Xylo"
        assert stale_channel_ids(session, [LOVED.id, NEUTRAL.id], now=T0) == [NEUTRAL.id]
        assert stale_channel_ids(session, [LOVED.id], now=T0 + timedelta(days=8)) == [LOVED.id]
    assert stored is not None
    assert [(c.channel_id, c.subscribed, c.subscriber_count) for c in stored] == [
        (X.id, False, 1000),
        (Y.id, False, 1000),
        (NEUTRAL.id, True, 1000),
    ]
    assert stored[0].thumbnail_url == "https://yt3.example/x.jpg"


def test_refresh_replaces_stale_featured_channels(
    sessions: sessionmaker[Session], gateway: FakeGateway, curated: None
) -> None:
    refresh(sessions, gateway, [LOVED.id], now=T0)
    gateway.add_featured(LOVED.id, [Z])

    refresh(sessions, gateway, [LOVED.id], now=T0 + timedelta(days=8))

    with sessions() as session:
        stored = stored_featured(session, LOVED.id)
    assert stored is not None and [c.channel_id for c in stored] == [Z.id]


def test_refresh_keeps_going_when_a_channel_fails(
    sessions: sessionmaker[Session], gateway: FakeGateway, curated: None
) -> None:
    gateway.fail("get_featured_channels", LOVED.id, RateLimitedError("slow down"))

    report = refresh(sessions, gateway, [LOVED.id, LIKED.id], now=T0)

    assert report.refreshed == [LIKED.id]
    assert list(report.failed) == [LOVED.id]
    with sessions() as session:
        assert stored_featured(session, LOVED.id) is None


def test_suggestions_rank_by_how_many_liked_channels_feature_them(
    sessions: sessionmaker[Session], gateway: FakeGateway, curated: None
) -> None:
    refresh(sessions, gateway, [LOVED.id, LIKED.id, RATED.id, NEUTRAL.id, MUTED.id], now=T0)

    with sessions() as session:
        suggestions = suggested_channels(session)

    # Y and Z are featured twice, at best first; Y has more subscribers. Subscribed channels
    # (NEUTRAL, LOVED), and those featured only by unliked (W) or muted (V) channels,
    # are left out.
    assert [s.channel_id for s in suggestions] == [Y.id, Z.id, X.id]
    assert suggestions[0].featured_by == [
        ChannelRef(LOVED.id, "Loved"),
        ChannelRef(LIKED.id, "Liked"),
    ]
    assert suggestions[1].featured_by == [
        ChannelRef(LIKED.id, "Liked"),
        ChannelRef(RATED.id, "Rated"),
    ]
    assert (suggestions[0].subscriber_count, suggestions[1].subscriber_count) == (1000, None)
    with sessions() as session:
        assert [s.channel_id for s in suggested_channels(session, limit=1)] == [Y.id]


def test_subscribing_removes_a_suggestion(
    sessions: sessionmaker[Session], gateway: FakeGateway, curated: None
) -> None:
    refresh(sessions, gateway, [LOVED.id, LIKED.id], now=T0)
    subscribe(sessions, gateway, Y)

    with sessions() as session:
        assert [s.channel_id for s in suggested_channels(session)] == [X.id, Z.id]


def test_suggest_fetches_liked_channels_never_fetched(
    sessions: sessionmaker[Session], gateway: FakeGateway, curated: None
) -> None:
    refresh(sessions, gateway, [LOVED.id], now=T0)
    gateway.calls.clear()

    suggestions = suggest(sessions, gateway, max_fetches=1, now=T0 + timedelta(days=30))

    # LOVED is stale but was fetched before: only the first never-fetched one is fetched.
    assert gateway.calls == [("get_featured_channels", LIKED.id)]
    assert [s.channel_id for s in suggestions] == [Y.id, X.id, Z.id]


def test_featured_channels_reads_through_storage(
    sessions: sessionmaker[Session], gateway: FakeGateway, curated: None
) -> None:
    first = featured_channels(sessions, gateway, LOVED.id, now=T0)
    cached = featured_channels(sessions, gateway, LOVED.id, now=T0 + timedelta(days=1))

    assert [c.channel_id for c in first] == [X.id, Y.id, NEUTRAL.id]
    assert cached == first
    assert gateway.calls.count(("get_featured_channels", LOVED.id)) == 1


def test_featured_channels_of_an_unknown_channel_are_not_stored(
    sessions: sessionmaker[Session], gateway: FakeGateway, curated: None
) -> None:
    featured = featured_channels(sessions, gateway, W.id, now=T0)
    with sessions.begin() as session:
        assert stored_featured(session, W.id) is None

    assert featured == []
    featured = featured_channels(sessions, gateway, NEUTRAL.id, now=T0)
    assert [(c.channel_id, c.title, c.subscribed) for c in featured] == [(W.id, "Wren", False)]


def test_featured_channels_falls_back_to_a_stale_copy(
    sessions: sessionmaker[Session], gateway: FakeGateway, curated: None
) -> None:
    featured_channels(sessions, gateway, LOVED.id, now=T0)
    gateway.fail("get_featured_channels", LOVED.id, ExtractionError("broken"))
    gateway.fail("get_featured_channels", LIKED.id, ExtractionError("broken"))

    stale = featured_channels(sessions, gateway, LOVED.id, now=T0 + timedelta(days=30))
    assert [c.channel_id for c in stale] == [X.id, Y.id, NEUTRAL.id]
    with pytest.raises(ExtractionError):
        featured_channels(sessions, gateway, LIKED.id, now=T0)


def test_source_finds_uploads_of_suggested_channels(
    sessions: sessionmaker[Session], gateway: FakeGateway, curated: None
) -> None:
    rate(sessions, "y0yyyyyyyyy", Y, 6.3)  # rated: never a candidate
    source = ChannelGraphSource(sessions, gateway, max_channels=2, per_channel=2, now=T0)

    report = generate([source], sessions=sessions, now=T0)

    assert report.new == {CHANNEL_GRAPH: ["y1yyyyyyyyy", "z0zzzzzzzzz", "z1zzzzzzzzz"]}
    with sessions() as session:
        pool = list_candidates(session, source=CHANNEL_GRAPH)
        stored = session.execute(
            text("SELECT channel_id, duration_seconds FROM videos WHERE id = 'z0zzzzzzzzz'")
        ).one()
    assert sorted((c.video_id, c.source_detail) for c in pool) == [
        ("y1yyyyyyyyy", LOVED.id),
        ("z0zzzzzzzzz", LIKED.id),
        ("z1zzzzzzzzz", LIKED.id),
    ]
    assert tuple(stored) == (Z.id, 600)
    # Featured channels of the liked channels were fetched, the others' weren't.
    fetched = [target for op, target in gateway.calls if op == "get_featured_channels"]
    assert fetched == [LOVED.id, LIKED.id, RATED.id]


def test_source_skips_channels_that_fail(
    sessions: sessionmaker[Session], gateway: FakeGateway, curated: None
) -> None:
    gateway.fail("get_featured_channels", LOVED.id, UnavailableError("gone"))
    gateway.fail("get_channel_uploads", Z.id, UnavailableError("gone"))

    found = ChannelGraphSource(sessions, gateway, per_channel=1, now=T0).fetch()

    assert [(f.video_id, f.source_detail) for f in found] == [("y0yyyyyyyyy", LIKED.id)]


def test_source_fails_when_every_call_fails(
    sessions: sessionmaker[Session], gateway: FakeGateway, curated: None
) -> None:
    for channel in (LOVED, LIKED, RATED):
        gateway.fail("get_featured_channels", channel.id, ExtractionError("blocked"))

    report = generate([ChannelGraphSource(sessions, gateway, now=T0)], sessions=sessions)

    assert report.failed == {CHANNEL_GRAPH: "blocked"}


def test_source_without_liked_channels_finds_nothing(
    sessions: sessionmaker[Session], gateway: FakeGateway
) -> None:
    subscribe(sessions, gateway, NEUTRAL)
    gateway.calls.clear()

    assert ChannelGraphSource(sessions, gateway, now=T0).fetch() == []
    assert gateway.calls == []
