import json
import math
import random
from collections.abc import Callable, Collection, Iterator, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import channel_hides, feeds
from homefeed_core.candidates import (
    CHANNEL_GRAPH,
    RELATED,
    SAVED_SEARCH,
    SUBSCRIPTION,
    TAG,
    record,
)
from homefeed_core.composer import ChannelRatings, VideoRef
from homefeed_core.config import Settings
from homefeed_core.curation import add_keyword_mute, subscribe_tag
from homefeed_core.db import open_database
from homefeed_core.embeddings import EMBEDDING_DIMENSIONS, StubEmbeddingProvider, store_embedding
from homefeed_core.enricher import Enricher, enrich_candidates, get_features
from homefeed_core.feedback import LESS, MORE, set_feedback
from homefeed_core.gateway.fake import FakeGateway, make_channel, make_video
from homefeed_core.llm_tags import TAG_PROMPT_VERSION, LLMTags, store_tags
from homefeed_core.model_features import FEATURE_NAMES
from homefeed_core.ranker import SIMILARITY_WEIGHT
from homefeed_core.ranking_models import RidgeModel, activate, record_version, save_model
from homefeed_core.ratings import set_rating
from homefeed_core.tags import ProposedTag, remove_video_tag, resolve_tag, set_llm_tags
from homefeed_core.user_settings import update_user_settings
from homefeed_core.watch_events import record_watch_event

NOW = datetime(2026, 10, 12, 6, 0, tzinfo=UTC)
TODAY = date(2026, 10, 12)
LOVED = "UC" + "l" * 22
PLAIN = "UC" + "p" * 22
MUTED = "UC" + "m" * 22
PINNED = "UC" + "x" * 22
GONE = "UC" + "g" * 22  # unsubscribed
# Exploration has tests of its own; the rest expect a purely score-ordered feed.
SETTINGS = Settings(feed_size=15, feed_exploration_slots=0)


def vid(channel_id: str, n: int) -> str:
    return f"{channel_id[2]}{n:010d}"


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    with factory.begin() as session:
        for channel_id, prefs in [
            (LOVED, {"prior": "love"}),
            (PLAIN, {}),
            (MUTED, {"muted": 1}),
            (PINNED, {"pinned": 1}),
            (GONE, None),
        ]:
            session.execute(
                text("INSERT INTO channels (id, title, handle) VALUES (:id, :title, :handle)"),
                {"id": channel_id, "title": f"Channel {channel_id[2]}", "handle": "@h"},
            )
            if prefs is not None:
                session.execute(
                    text(
                        "INSERT INTO channel_prefs (channel_id, prior, pinned, muted) "
                        "VALUES (:id, :prior, :pinned, :muted)"
                    ),
                    {"id": channel_id, "prior": "neutral", "pinned": 0, "muted": 0, **prefs},
                )
            add_videos(session, channel_id, range(4))
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def add_videos(
    session: Session, channel_id: str, numbers: range, *, seen: datetime = NOW, **columns: object
) -> None:
    for n in numbers:
        session.execute(
            text(
                """
                INSERT INTO videos (id, channel_id, title, published_at, duration_seconds,
                                    live_status, is_short)
                VALUES (:id, :channel, :title, :published, :duration, :live, :short)
                """
            ),
            {
                "id": vid(channel_id, n),
                "channel": channel_id,
                "title": f"Video {n}",
                "published": f"2026-10-{n + 1:02d}T00:00:00.000Z",
                "duration": columns.get("duration"),
                "live": columns.get("live"),
                "short": columns.get("short", 0),
            },
        )
        record(
            session,
            [vid(channel_id, n)],
            source=SUBSCRIPTION,
            source_detail=channel_id,
            now=seen - timedelta(hours=1),
        )


def build(
    sessions: sessionmaker[Session], *, feed_date: date | None = None, settings: Settings = SETTINGS
) -> feeds.Feed:
    with sessions.begin() as session:
        return feeds.build_feed(
            session, feed_date=feed_date, settings=settings, rng=random.Random(0), now=NOW
        )


def build_at(sessions: sessionmaker[Session], now: datetime) -> feeds.Feed:
    """A feed built at `now`, with the candidates first seen an hour before `NOW` still
    inside the candidate window."""
    with sessions.begin() as session:
        return feeds.build_feed(
            session,
            feed_date=TODAY,
            settings=Settings(feed_size=15, feed_exploration_slots=0, feed_candidate_days=60),
            rng=random.Random(0),
            now=now,
        )


def test_build_feed_ranks_composes_and_stores(sessions: sessionmaker[Session]) -> None:
    feed = build(sessions, feed_date=TODAY)

    channels = [item.channel_id for item in feed.items]
    assert feed.date == TODAY and feed.model_version is None
    # Pins first, then the loved channel, at most 2 per channel; muted and unsubscribed out.
    assert channels == [PINNED, PINNED, LOVED, LOVED, PLAIN, PLAIN]
    assert [item.position for item in feed.items] == list(range(6))
    first = feed.items[0]
    assert first.is_pinned and not first.is_exploration
    assert first.video_id == vid(PINNED, 3)  # newest first among equal scores
    assert first.channel_title == "Channel x"
    assert first.title == "Video 3"
    assert feed.items[2].breakdown.channel == pytest.approx(0.8)
    assert feed.items[2].score == pytest.approx(feed.items[2].breakdown.final)
    assert feed.items[2].explanation == "New from your subscriptions · channel you love"

    with sessions() as session:
        stored = session.execute(text("SELECT breakdown FROM feed_items LIMIT 1")).scalar_one()
        assert set(json.loads(stored)) == {
            "model",
            "alpha",
            "channel",
            "similarity",
            "tags",
            "final",
            "similarity_features",
        }
        assert feeds.get_feed(session, TODAY) == feed


def test_a_channel_muted_for_a_time_is_left_out_until_the_mute_runs_out(
    sessions: sessionmaker[Session],
) -> None:
    until = NOW + timedelta(days=30)
    with sessions.begin() as session:
        session.execute(
            text("UPDATE channel_prefs SET muted_until = :until WHERE channel_id = :id"),
            {"id": PLAIN, "until": until.strftime("%Y-%m-%dT%H:%M:%S.000Z")},
        )
        assert feeds.load_curation(session, now=NOW)[PLAIN].muted
        assert feeds.load_curation(session, now=until - timedelta(seconds=1))[PLAIN].muted
        assert not feeds.load_curation(session, now=until)[PLAIN].muted

    muted = build(sessions)
    later = build_at(sessions, until)

    assert PLAIN not in {item.channel_id for item in muted.items}
    assert PLAIN in {item.channel_id for item in later.items}


def test_build_feed_stores_exploration_slots(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add_videos(session, LOVED, range(4, 10))
        scores = [8, 6, 5, 9, 2]  # 5 ratings: not explored
        for n, score in enumerate(scores):
            set_rating(session, vid(LOVED, n), score)
        set_rating(session, vid(PLAIN, 0), 3)
        assert feeds.load_channel_ratings(session) == {
            LOVED: ChannelRatings(good=3, not_good=2),
            PLAIN: ChannelRatings(good=0, not_good=1),
        }

    feed = build(sessions, settings=Settings(feed_size=15, feed_exploration_slots=3))

    explored = [item for item in feed.items if item.is_exploration]
    # PLAIN is the only non-pinned channel with fewer than 5 ratings (LOVED has 5).
    assert [(item.position, item.channel_id) for item in explored] == [(2, PLAIN)]
    assert explored[0].selection_probability == 1.0
    assert explored[0].explanation.startswith("Exploring: channel with 1 rating")
    with sessions() as session:
        stored = session.execute(
            text(
                "SELECT video_id, selection_probability FROM feed_items "
                "WHERE feed_id = :id AND is_exploration = 1"
            ),
            {"id": feed.id},
        ).all()
    assert stored == [(explored[0].video_id, 1.0)]


def test_feed_size_is_exact_with_enough_candidates(sessions: sessionmaker[Session]) -> None:
    feed = build(sessions, settings=Settings(feed_size=3))

    assert len(feed.items) == 3


def extend(sessions: sessionmaker[Session], feed_id: int, size: int) -> feeds.Feed | None:
    with sessions.begin() as session:
        return feeds.extend_feed(
            session,
            feed_id,
            settings=Settings(feed_size=size, feed_exploration_slots=0),
            rng=random.Random(0),
            now=NOW,
        )


def test_extend_feed_appends_the_next_picks(sessions: sessionmaker[Session]) -> None:
    feed = build(sessions, settings=Settings(feed_size=5, feed_exploration_slots=0))

    extended = extend(sessions, feed.id, 5)

    assert extended is not None
    assert extended.id == feed.id
    assert [item.video_id for item in extended.items[:5]] == [i.video_id for i in feed.items]
    assert len(extended.items) == 10
    assert [item.position for item in extended.items] == list(range(10))
    video_ids = [item.video_id for item in extended.items]
    assert len(set(video_ids)) == 10
    with sessions.begin() as session:
        assert feeds.get_feed(session, TODAY) == extended


def test_extend_feed_returns_the_feed_unchanged_when_the_pool_is_exhausted(
    sessions: sessionmaker[Session],
) -> None:
    feed = build(sessions, settings=Settings(feed_size=5, feed_exploration_slots=0))
    for _ in range(10):
        extended = extend(sessions, feed.id, 5)
        assert extended is not None
        if extended.items == feed.items:
            break
        feed = extended
    else:
        pytest.fail("The pool never ran out")

    assert extend(sessions, feed.id, 5) == feed
    assert len({item.video_id for item in feed.items}) == len(feed.items)
    assert [item.position for item in feed.items] == list(range(len(feed.items)))


def test_extend_feed_of_a_missing_feed_is_none(sessions: sessionmaker[Session]) -> None:
    assert extend(sessions, 999, 5) is None


OUTSIDE = ["UC" + c * 22 for c in "abc"]  # not subscribed


def add_outside_videos(session: Session) -> None:
    """Three videos from each of three unsubscribed channels, found by sources other than
    subscriptions, and one from a subscribed channel found by a related video."""
    for channel_id, source in zip(OUTSIDE, [RELATED, CHANNEL_GRAPH, TAG], strict=True):
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, :title)"),
            {"id": channel_id, "title": f"Outside {channel_id[2]}"},
        )
        for n in range(3):
            session.execute(
                text("INSERT INTO videos (id, channel_id, title) VALUES (:id, :channel, 'x')"),
                {"id": vid(channel_id, n), "channel": channel_id},
            )
        record(session, [vid(channel_id, n) for n in range(3)], source=source, now=NOW)
    add_videos(session, LOVED, range(9, 10))
    session.execute(text("DELETE FROM candidates WHERE video_id = :id"), {"id": vid(LOVED, 9)})
    record(session, [vid(LOVED, 9)], source=RELATED, now=NOW)


def discover(sessions: sessionmaker[Session], size: int = 10) -> list[feeds.DiscoveryItem]:
    with sessions() as session:
        return feeds.discover(session, size=size, settings=SETTINGS, now=NOW)


def test_discover_picks_one_video_per_channel_from_outside_the_subscriptions(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        add_outside_videos(session)

    items = discover(sessions)

    assert sorted(item.channel_id for item in items) == OUTSIDE
    assert {item.source for item in items} == {RELATED, CHANNEL_GRAPH, TAG}
    assert items[0].channel_title.startswith("Outside ")
    assert all(item.explanation for item in items)
    assert [item.score for item in items] == sorted((item.score for item in items), reverse=True)
    assert len(discover(sessions, size=2)) == 2


def test_discover_leaves_out_todays_feed_and_watched_videos(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        add_outside_videos(session)
        for n in range(3):
            set_rating(session, vid(OUTSIDE[0], n), 7)
    in_feed = {item.video_id for item in build(sessions, feed_date=TODAY).items}

    shown = {item.video_id for item in discover(sessions)}

    assert in_feed & {vid(c, n) for c in OUTSIDE for n in range(3)}  # the feed has some
    assert len(shown) == 2 and shown.isdisjoint(in_feed)
    assert OUTSIDE[0] not in {video_id[0] for video_id in shown}


def test_discover_with_an_empty_pool(tmp_path: Path) -> None:
    factory = open_database(tmp_path / "homefeed.sqlite")
    with factory() as session:
        assert feeds.discover(session, settings=SETTINGS, now=NOW) == []


def test_watched_and_dismissed_are_left_out(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_rating(session, vid(LOVED, 3), 6)
    first = build(sessions)
    with sessions.begin() as session:
        session.execute(
            text("UPDATE feed_items SET dismissed_at = 'x' WHERE video_id = :id"),
            {"id": vid(LOVED, 2)},
        )

    second = build(sessions)

    shown = {item.video_id for item in second.items}
    assert vid(LOVED, 3) not in {item.video_id for item in first.items}
    assert vid(LOVED, 2) in {item.video_id for item in first.items}
    assert {vid(LOVED, 3), vid(LOVED, 2)}.isdisjoint(shown)
    assert {vid(LOVED, 1), vid(LOVED, 0)} <= shown


def test_dismissing_an_item_records_when_and_why(sessions: sessionmaker[Session]) -> None:
    item = build(sessions).items[2]

    with sessions.begin() as session:
        dismissed = feeds.dismiss_feed_item(session, item.id, "  Not in the mood  ", now=NOW)

    assert dismissed is not None
    assert dismissed.dismissed_at == "2026-10-12T06:00:00.000Z"
    assert dismissed.dismiss_reason == "Not in the mood"
    assert dismissed == replace(
        item, dismissed_at=dismissed.dismissed_at, dismiss_reason="Not in the mood"
    )
    with sessions() as session:
        assert feeds.get_feed_item(session, item.id) == dismissed


def test_dismissing_without_a_reason(sessions: sessionmaker[Session]) -> None:
    item = build(sessions).items[0]

    with sessions.begin() as session:
        dismissed = feeds.dismiss_feed_item(session, item.id, "   ", now=NOW)

    assert dismissed is not None
    assert dismissed.dismissed_at is not None
    assert dismissed.dismiss_reason is None


def test_dismissing_again_keeps_the_first_time_and_updates_the_reason(
    sessions: sessionmaker[Session],
) -> None:
    item = build(sessions).items[0]
    with sessions.begin() as session:
        feeds.dismiss_feed_item(session, item.id, "Clickbait", now=NOW)

    with sessions.begin() as session:
        later = NOW + timedelta(minutes=5)
        renamed = feeds.dismiss_feed_item(session, item.id, "Too long", now=later)
        kept = feeds.dismiss_feed_item(session, item.id, None, now=later)

    assert renamed is not None and kept is not None
    assert renamed.dismissed_at == kept.dismissed_at == "2026-10-12T06:00:00.000Z"
    assert renamed.dismiss_reason == kept.dismiss_reason == "Too long"


def test_dismissing_a_missing_item_returns_none(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        assert feeds.dismiss_feed_item(session, 12345) is None
        assert feeds.get_feed_item(session, 12345) is None


def test_dismiss_reason_length_is_limited(sessions: sessionmaker[Session]) -> None:
    item = build(sessions).items[0]

    with sessions.begin() as session, pytest.raises(ValueError, match="at most"):
        feeds.dismiss_feed_item(session, item.id, "x" * (feeds.DISMISS_REASON_MAX_LENGTH + 1))
    with sessions() as session:
        assert feeds.get_feed_item(session, item.id) == item


def test_dismissed_videos_are_left_out_of_later_feeds(sessions: sessionmaker[Session]) -> None:
    first = build(sessions)
    dismissed = first.items[2].video_id
    with sessions.begin() as session:
        feeds.dismiss_feed_item(session, first.items[2].id, "Not interested")

    second = build(sessions)

    assert dismissed not in {item.video_id for item in second.items}
    with sessions() as session:
        # The earlier feed keeps the item on record, marked dismissed.
        kept = feeds.get_feed_item(session, first.items[2].id)
        assert kept is not None and kept.dismiss_reason == "Not interested"


def test_played_videos_are_left_out(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        record_watch_event(session, vid(LOVED, 3), "play", 0.0, 600.0)
        record_watch_event(session, vid(LOVED, 3), "close", 30.0, 600.0)
        # Opened but never played: still a candidate.
        record_watch_event(session, vid(LOVED, 2), "close", 0.0, 600.0)

    shown = {item.video_id for item in build(sessions).items}

    assert vid(LOVED, 3) not in shown
    assert vid(LOVED, 2) in shown


def test_items_watched_since_the_feed_was_built_are_marked(
    sessions: sessionmaker[Session],
) -> None:
    feed = build(sessions)
    played, rated, opened = feed.items[2], feed.items[3], feed.items[4]
    assert not any(item.watched for item in feed.items)
    with sessions.begin() as session:
        record_watch_event(session, played.video_id, "play", 0.0, 600.0)
        set_rating(session, rated.video_id, 7)
        # Opened but never played: not watched.
        record_watch_event(session, opened.video_id, "close", 0.0, 600.0)

    with sessions() as session:
        reread = feeds.get_feed(session, feed.date)

    assert reread is not None
    assert [item.video_id for item in reread.items if item.watched] == [
        played.video_id,
        rated.video_id,
    ]


def channel_score_model() -> RidgeModel:
    """Predicts `0.5 * channel_score + 0.1`, ignoring every other feature."""
    coef = np.zeros(len(FEATURE_NAMES))
    coef[FEATURE_NAMES.index("channel_score")] = 0.5
    return RidgeModel(
        mean=np.zeros(len(FEATURE_NAMES)),
        scale=np.ones(len(FEATURE_NAMES)),
        coef=coef,
        intercept=0.1,
    )


def install_model(session: Session, data_dir: Path, *, path: str | None = None) -> int:
    """Store and activate `channel_score_model`; `path` overrides the file it points to."""
    stored = save_model(channel_score_model(), data_dir)
    version = record_version(
        session, path=path or stored, kind="ridge", spearman=0.5, mae=0.2, metrics={}
    )
    activate(session, version.id, now=NOW)
    return version.id


def test_active_model_is_blended_in_by_rating_count(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    with sessions.begin() as session:
        add_videos(session, PLAIN, range(10, 15))
        for n in range(10, 15):
            set_rating(session, vid(PLAIN, n), 6)
        version_id = install_model(session, tmp_path)

    feed = build(sessions, settings=SETTINGS.model_copy(update={"data_dir": tmp_path}))

    assert feed.model_version == str(version_id)
    assert feed.items
    for item in feed.items:
        b = item.breakdown
        assert b.alpha == pytest.approx(5 / 55)
        assert b.model == pytest.approx(0.5 * b.channel + 0.1)
        parts = b.alpha * b.model + b.channel + b.similarity + sum(b.tags.values())
        assert math.isclose(item.score, parts) and item.score == b.final
    with sessions() as session:
        assert feeds.get_feed(session, TODAY) == feed
        [summary] = feeds.list_feeds(session)
        assert summary.model_version == str(version_id)
        stored = session.execute(text("SELECT breakdown FROM feed_items LIMIT 1")).scalar_one()
        assert json.loads(stored)["alpha"] == pytest.approx(5 / 55)


def test_unloadable_active_model_ranks_rules_only(
    sessions: sessionmaker[Session], tmp_path: Path
) -> None:
    with sessions.begin() as session:
        set_rating(session, vid(PLAIN, 0), 6)
        install_model(session, tmp_path, path="ranking_models/missing.json")

    feed = build(sessions, settings=SETTINGS.model_copy(update={"data_dir": tmp_path}))

    assert feed.model_version is None
    assert all(item.breakdown.alpha == 0 and item.breakdown.model == 0 for item in feed.items)


def test_ratings_shape_channel_score(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add_videos(session, PLAIN, range(10, 15))
        for n in range(10, 15):
            set_rating(session, vid(PLAIN, n), 10)

    feed = build(sessions)

    plain = [item for item in feed.items if item.channel_id == PLAIN]
    assert plain[0].breakdown.channel == pytest.approx(5 / 10)
    assert plain[0].explanation.endswith("channel score +0.50 from 5 ratings")
    assert plain[0].breakdown.alpha == 0.0


def test_hard_filters_and_unknown_metadata(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        session.execute(text("DELETE FROM candidates"))
        add_videos(session, PLAIN, range(20, 21), short=1)
        add_videos(session, PLAIN, range(21, 22), live="is_upcoming")
        add_videos(session, PLAIN, range(22, 23), duration=30)
        add_videos(session, PLAIN, range(23, 24), duration=10_000)
        add_videos(session, LOVED, range(24, 25), duration=600)
        add_videos(session, LOVED, range(25, 26))  # duration and live status unknown

    feed = build(sessions, settings=Settings(feed_max_duration_seconds=3600))

    assert [item.video_id for item in feed.items] == [vid(LOVED, 25), vid(LOVED, 24)]


def test_muted_keywords_are_left_out(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        session.execute(text("DELETE FROM candidates"))
        add_videos(session, LOVED, range(30, 33))
        session.execute(
            text("UPDATE videos SET title = 'Crypto news' WHERE id = :id"), {"id": vid(LOVED, 30)}
        )
        session.execute(
            text("UPDATE videos SET description = 'Sponsored by a CRYPTO exchange' WHERE id = :id"),
            {"id": vid(LOVED, 31)},
        )
        add_keyword_mute(session, "crypto")

    feed = build(sessions)

    assert [item.video_id for item in feed.items] == [vid(LOVED, 32)]


def test_tag_boosts_reorder_and_appear_in_the_breakdown(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        session.execute(text("DELETE FROM candidates"))
        add_videos(session, PLAIN, range(50, 54))
        set_llm_tags(session, vid(PLAIN, 50), [ProposedTag("Drama", 1.0)], prompt_version=1)
        set_llm_tags(session, vid(PLAIN, 52), [ProposedTag("Woodworking", 1.0)], prompt_version=1)
        woodworking, drama = resolve_tag(session, "Woodworking"), resolve_tag(session, "Drama")
        assert woodworking is not None and drama is not None
        subscribe_tag(session, woodworking, weight=0.6)
        subscribe_tag(session, drama, weight=-1.0)

    feed = build(sessions, settings=Settings(feed_size=15))

    plain = [item for item in feed.items if item.channel_id == PLAIN]
    by_id = {item.video_id: item for item in plain}
    # At most 2 per channel: the boosted one, then the newer unboosted.
    assert [item.video_id for item in plain] == [vid(PLAIN, 52), vid(PLAIN, 53)]
    assert by_id[vid(PLAIN, 52)].breakdown.tags == {"Woodworking": pytest.approx(0.6)}
    assert by_id[vid(PLAIN, 53)].breakdown.tags == {}
    assert by_id[vid(PLAIN, 52)].score == pytest.approx(0.6)
    with sessions() as session:
        stored = session.execute(
            text("SELECT breakdown FROM feed_items WHERE video_id = :id"), {"id": vid(PLAIN, 52)}
        ).scalar_one()
    assert json.loads(stored)["tags"] == {"Woodworking": pytest.approx(0.6)}


def test_tag_subscriptions_boost_tagged_videos_in_the_feed(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        session.execute(text("DELETE FROM candidates"))
        add_videos(session, PLAIN, range(50, 54))
        set_llm_tags(
            session,
            vid(PLAIN, 50),
            [ProposedTag("rust", 0.8), ProposedTag("go", 1.0)],
            prompt_version=1,
        )
        set_llm_tags(session, vid(PLAIN, 51), [ProposedTag("rust", 0.9)], prompt_version=1)
        remove_video_tag(session, vid(PLAIN, 51), "rust")  # a removed link does not count
        rust = resolve_tag(session, "rust")
        assert rust is not None
        subscribe_tag(session, rust, weight=0.5)

    feed = build(sessions, settings=Settings(feed_size=15))

    plain = {item.video_id: item for item in feed.items if item.channel_id == PLAIN}
    assert plain[vid(PLAIN, 50)].breakdown.tags == {"rust": pytest.approx(0.4)}
    assert all(item.breakdown.tags == {} for key, item in plain.items() if key != vid(PLAIN, 50))
    assert plain[vid(PLAIN, 50)].score == pytest.approx(0.4)


def test_candidate_window(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add_videos(session, PLAIN, range(30, 31), seen=NOW - timedelta(days=30))

    feed = build(sessions)

    assert vid(PLAIN, 30) not in {item.video_id for item in feed.items}


def test_empty_pool_stores_an_empty_feed(tmp_path: Path) -> None:
    factory = open_database(tmp_path / "empty.sqlite")
    feed = build(factory)

    assert feed.items == []
    with factory() as session:
        assert feeds.list_feeds(session)[0].item_count == 0
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


def test_latest_feed_per_date_and_history(sessions: sessionmaker[Session]) -> None:
    yesterday = build(sessions, feed_date=TODAY - timedelta(days=1))
    build(sessions, feed_date=TODAY)
    refreshed = build(sessions, feed_date=TODAY, settings=Settings(feed_size=2))

    with sessions() as session:
        assert feeds.get_feed(session, TODAY) == refreshed
        assert feeds.get_feed(session, TODAY - timedelta(days=2)) is None
        history = feeds.list_feeds(session)
    assert [(s.id, s.date, s.item_count) for s in history] == [
        (refreshed.id, TODAY, 2),
        (yesterday.id, TODAY - timedelta(days=1), 6),
    ]


def test_refresh_feed_polls_then_builds(sessions: sessionmaker[Session]) -> None:
    calls: list[str] = []

    def poll() -> None:
        calls.append("poll")
        with sessions.begin() as session:
            add_videos(session, LOVED, range(40, 41))

    feed = feeds.refresh_feed(
        sessions=sessions, poll=poll, settings=SETTINGS, rng=random.Random(0), now=NOW
    )

    assert calls == ["poll"]
    assert feed.date == feeds.local_today(NOW)
    assert vid(LOVED, 40) in {item.video_id for item in feed.items}


def test_refresh_feed_survives_a_failing_poll(sessions: sessionmaker[Session]) -> None:
    def poll() -> None:
        raise RuntimeError("YouTube is down")

    feed = feeds.refresh_feed(sessions=sessions, poll=poll, settings=SETTINGS, now=NOW)

    assert len(feed.items) == 6


def test_refresh_feed_enriches_candidates_before_ranking(
    sessions: sessionmaker[Session],
) -> None:
    # RSS doesn't give durations; enrichment finds that one candidate is a Short.
    gateway = FakeGateway()
    channel = make_channel(LOVED)
    gateway.add_channel(
        channel,
        [
            make_video(vid(LOVED, n), channel=channel, duration_seconds=30 if n == 3 else 600)
            for n in range(4)
        ],
    )
    enricher = Enricher(sessions, gateway, StubEmbeddingProvider(), now=lambda: NOW)
    calls: list[str] = []

    def enrich() -> None:
        calls.append("enrich")
        enrich_candidates(enricher=enricher, sessions=sessions, settings=SETTINGS, now=NOW)

    feed = feeds.refresh_feed(
        sessions=sessions,
        poll=lambda: calls.append("poll"),
        enrich=enrich,
        settings=SETTINGS,
        rng=random.Random(0),
        now=NOW,
    )

    assert calls == ["poll", "enrich"]
    loved = [item.video_id for item in feed.items if item.channel_id == LOVED]
    # The newest upload is the Short, so the next two fill the channel's slots.
    assert sorted(loved) == [vid(LOVED, 1), vid(LOVED, 2)]
    with sessions() as session:
        features = get_features(session, vid(LOVED, 3))
    assert features is not None and features.duration_seconds == 30


def test_refresh_feed_survives_a_failing_enrichment(sessions: sessionmaker[Session]) -> None:
    def enrich() -> None:
        raise RuntimeError("model download failed")

    feed = feeds.refresh_feed(
        sessions=sessions, poll=None, enrich=enrich, settings=SETTINGS, now=NOW
    )

    assert len(feed.items) == 6


LOVED_TOO = "UC" + "t" * 22


def unit(i: int) -> list[float]:
    return [1.0 if j == i else 0.0 for j in range(EMBEDDING_DIMENSIONS)]


def test_similarity_to_rated_tiers_shapes_ranking(sessions: sessionmaker[Session]) -> None:
    loved, hated = vid(PLAIN, 40), vid(PLAIN, 41)
    with sessions.begin() as session:
        session.execute(text("DELETE FROM candidates"))
        add_videos(session, PLAIN, range(40, 42), seen=NOW - timedelta(days=60))  # old
        set_rating(session, loved, 9)
        set_rating(session, hated, 2)
        store_embedding(session, loved, unit(0))
        store_embedding(session, hated, unit(1))
        add_videos(session, LOVED, range(42, 44))
        store_embedding(session, vid(LOVED, 42), unit(0))  # like the loved one
        store_embedding(session, vid(LOVED, 43), unit(1))  # like the hated one
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, 'Also loved')"), {"id": LOVED_TOO}
        )
        session.execute(
            text("INSERT INTO channel_prefs (channel_id, prior) VALUES (:id, 'love')"),
            {"id": LOVED_TOO},
        )
        add_videos(session, LOVED_TOO, range(44, 45))  # not enriched

    feed = build(sessions)

    assert [item.video_id for item in feed.items] == [
        vid(LOVED, 42),
        vid(LOVED_TOO, 44),
        vid(LOVED, 43),
    ]
    first, unenriched, last = (item.breakdown for item in feed.items)
    assert first.similarity == pytest.approx(SIMILARITY_WEIGHT)
    assert last.similarity == pytest.approx(-SIMILARITY_WEIGHT)
    assert unenriched.similarity == 0.0 and unenriched.similarity_features is None
    assert first.similarity_features is not None
    assert first.similarity_features.top_tier is not None
    assert first.similarity_features.top_tier.nearest_video_id == loved
    assert first.similarity_features.top_tier.max == pytest.approx(1.0)
    assert first.similarity_features.bottom_tier is not None
    assert first.similarity_features.bottom_tier.max == pytest.approx(0.0)
    for item in feed.items:
        assert item.score == pytest.approx(item.breakdown.final)


def test_explanations_name_the_nearest_top_tier_video(sessions: sessionmaker[Session]) -> None:
    loved = vid(PLAIN, 40)
    with sessions.begin() as session:
        session.execute(text("DELETE FROM candidates"))
        add_videos(session, PLAIN, range(40, 41), seen=NOW - timedelta(days=60))  # old
        set_rating(session, loved, 8)
        store_embedding(session, loved, unit(0))
        add_videos(session, PLAIN, range(41, 42))
        store_embedding(session, vid(PLAIN, 41), unit(0))

    feed = build(sessions)

    assert [item.explanation for item in feed.items] == [
        "New from your subscriptions · similar to “Video 40”, which you rated 8"
    ]
    with sessions.begin() as session:
        stored = session.execute(text("SELECT explanation FROM feed_items")).scalar_one()
    assert stored == feed.items[0].explanation


def shaped_by_marks(session: Session, loved: str, hated: str) -> None:
    """Two old videos with opposite embeddings, then candidates like one or the other,
    like `test_similarity_to_rated_tiers_shapes_ranking` (the caller rates or marks the
    old ones)."""
    session.execute(text("DELETE FROM candidates"))
    add_videos(session, PLAIN, range(40, 42), seen=NOW - timedelta(days=60))  # old
    store_embedding(session, loved, unit(0))
    store_embedding(session, hated, unit(1))
    add_videos(session, LOVED, range(42, 44))
    store_embedding(session, vid(LOVED, 42), unit(0))  # like the loved one
    store_embedding(session, vid(LOVED, 43), unit(1))  # like the hated one


def test_feedback_shapes_ranking_like_a_top_and_bottom_tier_rating(
    sessions: sessionmaker[Session],
) -> None:
    loved, hated = vid(PLAIN, 40), vid(PLAIN, 41)
    with sessions.begin() as session:
        shaped_by_marks(session, loved, hated)
        set_feedback(session, loved, MORE)
        set_feedback(session, hated, LESS)

    feed = build(sessions)

    assert [item.video_id for item in feed.items] == [vid(LOVED, 42), vid(LOVED, 43)]
    first, last = feed.items
    assert first.breakdown.similarity == pytest.approx(SIMILARITY_WEIGHT)
    assert last.breakdown.similarity == pytest.approx(-SIMILARITY_WEIGHT)
    assert first.breakdown.similarity_features is not None
    assert first.breakdown.similarity_features.top_tier is not None
    assert first.breakdown.similarity_features.top_tier.nearest_video_id == loved
    assert first.breakdown.similarity_features.bottom_tier is not None
    assert first.breakdown.similarity_features.bottom_tier.nearest_video_id == hated


def test_explanations_name_the_nearest_video_the_user_wanted_more_of(
    sessions: sessionmaker[Session],
) -> None:
    liked = vid(PLAIN, 40)
    with sessions.begin() as session:
        session.execute(text("DELETE FROM candidates"))
        add_videos(session, PLAIN, range(40, 41), seen=NOW - timedelta(days=60))  # old
        set_feedback(session, liked, MORE)
        store_embedding(session, liked, unit(0))
        add_videos(session, PLAIN, range(41, 42))
        store_embedding(session, vid(PLAIN, 41), unit(0))

    feed = build(sessions)

    assert [item.explanation for item in feed.items] == [
        "New from your subscriptions · similar to “Video 40”, which you wanted more of"
    ]
    # An explicit rating changes how it is named.
    with sessions.begin() as session:
        set_rating(session, liked, 9)
    assert [item.explanation for item in build(sessions).items] == [
        "New from your subscriptions · similar to “Video 40”, which you rated 9"
    ]


def test_a_video_marked_more_like_this_does_not_push_itself_up_the_next_feed(
    sessions: sessionmaker[Session],
) -> None:
    marked = vid(PLAIN, 40)
    with sessions.begin() as session:
        session.execute(text("DELETE FROM candidates"))
        add_videos(session, PLAIN, range(40, 41))
        set_feedback(session, marked, MORE)
        store_embedding(session, marked, unit(0))

    feed = build(sessions)

    [item] = feed.items
    assert item.video_id == marked
    # It isn't compared with itself, so it is ranked on its own merits and says why.
    assert item.breakdown.similarity == 0.0
    assert item.breakdown.similarity_features is not None
    assert item.breakdown.similarity_features.top_tier is None
    assert item.explanation == "New from your subscriptions"


def test_a_video_marked_less_like_this_keeps_itself_down(
    sessions: sessionmaker[Session],
) -> None:
    marked = vid(PLAIN, 40)
    with sessions.begin() as session:
        session.execute(text("DELETE FROM candidates"))
        add_videos(session, PLAIN, range(40, 41))
        set_feedback(session, marked, LESS)
        store_embedding(session, marked, unit(0))

    [item] = build(sessions).items

    assert item.video_id == marked
    assert item.breakdown.similarity == pytest.approx(-SIMILARITY_WEIGHT)


def test_feedback_is_not_a_rating(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        shaped_by_marks(session, vid(PLAIN, 40), vid(PLAIN, 41))
        set_feedback(session, vid(PLAIN, 40), MORE)
        set_feedback(session, vid(PLAIN, 41), LESS)

        history = feeds.load_history(session)
        assert history.n_ratings == 0
        assert history.channel_ratings == {}
        assert feeds.load_channel_ratings(session) == {}
        # Marking a video is no reason to treat it as watched, either.
        assert not history.watched

    assert not any(item.watched for item in build(sessions).items)


def test_an_explicit_rating_wins_over_feedback(sessions: sessionmaker[Session]) -> None:
    more_but_bad, less_but_good, more_but_meh, plain_more, plain_less = (
        vid(PLAIN, n) for n in range(40, 45)
    )
    with sessions.begin() as session:
        add_videos(session, PLAIN, range(40, 45))
        for n, video_id in enumerate([more_but_bad, less_but_good, more_but_meh, plain_more]):
            store_embedding(session, video_id, unit(n))
        store_embedding(session, plain_less, unit(4))
        set_rating(session, more_but_bad, 2)
        set_rating(session, less_but_good, 9)
        set_rating(session, more_but_meh, 5)  # neither tier
        for video_id, signal in [
            (more_but_bad, MORE),
            (less_but_good, LESS),
            (more_but_meh, MORE),
            (plain_more, MORE),
            (plain_less, LESS),
        ]:
            set_feedback(session, video_id, signal)

        tiers = feeds.load_rated_tiers(session)

    assert set(tiers.top) == {less_but_good, plain_more}
    assert set(tiers.bottom) == {more_but_bad, plain_less}


def test_feedback_without_an_embedding_is_left_out_of_the_tiers(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        set_feedback(session, vid(PLAIN, 0), MORE)
        set_feedback(session, vid(PLAIN, 1), LESS)
        store_embedding(session, vid(PLAIN, 1), unit(1))

        tiers = feeds.load_rated_tiers(session)

    assert (set(tiers.top), set(tiers.bottom)) == (set(), {vid(PLAIN, 1)})


def test_video_refs_carry_ratings_and_feedback(sessions: sessionmaker[Session]) -> None:
    rated, more, less, plain = (vid(PLAIN, n) for n in range(4))
    with sessions.begin() as session:
        set_rating(session, rated, 8)
        set_feedback(session, rated, LESS)
        set_feedback(session, more, MORE)
        set_feedback(session, less, LESS)

        refs = feeds.load_video_refs(session, [rated, more, less, plain, "missing"])

    assert refs == {
        rated: VideoRef("Video 0", 8, feedback=-1),
        more: VideoRef("Video 1", feedback=1),
        less: VideoRef("Video 2", feedback=-1),
        plain: VideoRef("Video 3"),
    }


# What a card shows


def item_for(feed: feeds.Feed, video_id: str) -> feeds.FeedItem:
    [item] = [item for item in feed.items if item.video_id == video_id]
    return item


def test_items_say_whether_their_channel_is_subscribed(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add_outside_videos(session)

    feed = build(sessions, feed_date=TODAY)

    outside = [item for item in feed.items if item.channel_id in OUTSIDE]
    subscribed = [item for item in feed.items if item.channel_id not in OUTSIDE]
    assert outside and subscribed
    assert not any(item.channel_subscribed for item in outside)
    assert all(item.channel_subscribed for item in subscribed)


def test_items_start_with_nothing_to_show_but_the_basics(sessions: sessionmaker[Session]) -> None:
    [*_, item] = build(sessions).items

    assert (item.rating, item.feedback, item.watched_fraction) == (None, None, None)
    assert (item.tags, item.llm) == ((), None)


def test_items_carry_rating_feedback_progress_tags_and_llm_scores(
    sessions: sessionmaker[Session],
) -> None:
    feed = build(sessions)
    target, other = feed.items[2].video_id, feed.items[3].video_id
    with sessions.begin() as session:
        set_rating(session, target, 7)
        set_feedback(session, target, MORE)
        record_watch_event(session, target, "play", 0.0, 600.0)
        record_watch_event(session, target, "pause", 150.0, 600.0)
        set_llm_tags(
            session,
            target,
            [
                ProposedTag("Woodworking", 0.9),
                ProposedTag("Hand tools", 0.5),
                ProposedTag("Chisels", 0.7),
                ProposedTag("Sharpening", 0.3),
            ],
            prompt_version=TAG_PROMPT_VERSION,
        )
        store_tags(session, target, LLMTags("hobbies", 0.8, 0.1, 0.2), model="stub")

    with sessions() as session:
        reread = feeds.get_feed(session, feed.date)
        by_id = feeds.get_feed_item(session, feed.items[2].id)
    assert reread is not None

    item = item_for(reread, target)
    assert by_id == item
    assert item.watched and item.rating == 7 and item.feedback == 1
    assert item.watched_fraction == pytest.approx(0.25)
    # The three most confident tags, best first.
    assert [(tag.slug, tag.label) for tag in item.tags] == [
        ("woodworking", "Woodworking"),
        ("chisels", "Chisels"),
        ("hand-tools", "Hand tools"),
    ]
    assert item.llm == LLMTags("hobbies", 0.8, 0.1, 0.2)
    # Another item of the same feed is untouched.
    untouched = item_for(reread, other)
    assert (untouched.rating, untouched.feedback, untouched.watched_fraction) == (None,) * 3
    assert (untouched.tags, untouched.llm) == ((), None)


def test_items_show_the_latest_llm_scores_and_leave_out_removed_tags(
    sessions: sessionmaker[Session],
) -> None:
    feed = build(sessions)
    video_id = feed.items[0].video_id
    with sessions.begin() as session:
        store_tags(
            session, video_id, LLMTags("hobbies", 0.1, 0.9, 0.0), model="stub", prompt_version=1
        )
        store_tags(session, video_id, LLMTags("hobbies", 0.7, 0.2, 0.0), model="stub")
        set_llm_tags(
            session,
            video_id,
            [ProposedTag("Woodworking", 0.9), ProposedTag("Lathes", 0.8)],
            prompt_version=TAG_PROMPT_VERSION,
        )
        remove_video_tag(session, video_id, "woodworking")

    with sessions() as session:
        reread = feeds.get_feed(session, feed.date)
    assert reread is not None

    item = item_for(reread, video_id)
    assert item.llm == LLMTags("hobbies", 0.7, 0.2, 0.0)
    assert [tag.slug for tag in item.tags] == ["lathes"]


def test_items_report_how_far_through_the_video_the_user_got(
    sessions: sessionmaker[Session],
) -> None:
    feed = build(sessions)
    halfway, finished, barely, unplayed = (item.video_id for item in feed.items[:4])
    with sessions.begin() as session:
        record_watch_event(session, halfway, "play", 0.0, 600.0)
        record_watch_event(session, halfway, "close", 300.0, 600.0)
        record_watch_event(session, finished, "play", 0.0, 600.0)
        record_watch_event(session, finished, "ended", 600.0, 600.0)
        record_watch_event(session, barely, "play", 0.0, 600.0)
        record_watch_event(session, barely, "close", 2.0, 600.0)
        set_rating(session, unplayed, 6)  # rated, never played here

    with sessions() as session:
        reread = feeds.get_feed(session, feed.date)
    assert reread is not None

    fractions = {item.video_id: item.watched_fraction for item in reread.items[:4]}
    assert fractions == {halfway: 0.5, finished: 1.0, barely: None, unplayed: None}
    assert [item.watched for item in reread.items[:4]] == [True] * 4


# Undismissing


def test_undismissing_an_item_restores_it(sessions: sessionmaker[Session]) -> None:
    item = build(sessions).items[2]
    with sessions.begin() as session:
        feeds.dismiss_feed_item(session, item.id, "Clickbait", now=NOW)

    with sessions.begin() as session:
        restored = feeds.undismiss_feed_item(session, item.id)

    assert restored == item
    assert restored is not None
    assert (restored.dismissed_at, restored.dismiss_reason) == (None, None)
    with sessions() as session:
        assert feeds.get_feed_item(session, item.id) == item


def test_undismissing_an_item_that_is_not_dismissed_changes_nothing(
    sessions: sessionmaker[Session],
) -> None:
    item = build(sessions).items[0]

    with sessions.begin() as session:
        assert feeds.undismiss_feed_item(session, item.id) == item


def test_undismissing_a_missing_item_returns_none(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        assert feeds.undismiss_feed_item(session, 12345) is None


def test_an_undismissed_video_is_in_later_feeds_again(sessions: sessionmaker[Session]) -> None:
    first = build(sessions)
    video_id = first.items[2].video_id
    with sessions.begin() as session:
        feeds.dismiss_feed_item(session, first.items[2].id)
    assert video_id not in {item.video_id for item in build(sessions).items}

    with sessions.begin() as session:
        feeds.undismiss_feed_item(session, first.items[2].id)

    assert video_id in {item.video_id for item in build(sessions).items}


def test_a_video_dismissed_in_another_feed_stays_out_after_undismissing_one_item(
    sessions: sessionmaker[Session],
) -> None:
    first, second = build(sessions), build(sessions)  # two feeds of the day, same picks
    video_id = first.items[2].video_id
    with sessions.begin() as session:
        feeds.dismiss_feed_item(session, first.items[2].id)
        feeds.dismiss_feed_item(session, item_for(second, video_id).id)
        feeds.undismiss_feed_item(session, item_for(second, video_id).id)

    assert video_id not in {item.video_id for item in build(sessions).items}


# Discovery items


def test_discovery_items_carry_feedback_tags_and_llm_scores(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        add_outside_videos(session)
    [target, *_] = discover(sessions)
    with sessions.begin() as session:
        set_feedback(session, target.video_id, LESS)
        set_llm_tags(
            session, target.video_id, [ProposedTag("Birds", 0.9)], prompt_version=TAG_PROMPT_VERSION
        )
        store_tags(session, target.video_id, LLMTags("nature", 0.4, 0.8, 0.1), model="stub")

    items = {item.video_id: item for item in discover(sessions)}

    marked = items[target.video_id]
    assert marked.feedback == -1
    assert [tag.slug for tag in marked.tags] == ["birds"]
    assert marked.llm == LLMTags("nature", 0.4, 0.8, 0.1)
    assert not any(item.channel_subscribed for item in items.values())
    others = [item for video_id, item in items.items() if video_id != target.video_id]
    assert others and all(
        (item.feedback, item.tags, item.llm) == (None, (), None) for item in others
    )


# The share of a feed one topic may take


def add_followed_channels(session: Session, count: int, topic: str) -> None:
    """`count` subscribed channels with a video each, tagged with `topic`, which is
    followed (the boost puts these videos ahead of the rest)."""
    for n in range(count):
        channel_id = "UC" + "ABCDEFGHIJ"[n] * 22
        session.execute(
            text("INSERT INTO channels (id, title) VALUES (:id, 'Fan')"), {"id": channel_id}
        )
        session.execute(
            text("INSERT INTO channel_prefs (channel_id) VALUES (:id)"), {"id": channel_id}
        )
        add_videos(session, channel_id, range(60, 61))
        set_llm_tags(session, vid(channel_id, 60), [ProposedTag(topic, 1.0)], prompt_version=1)
    tag = resolve_tag(session, topic)
    assert tag is not None
    subscribe_tag(session, tag, weight=0.5)


def test_build_feed_caps_a_topic_by_the_stored_share(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add_followed_channels(session, 6, "Godot")
        update_user_settings(
            session, {"feed_size": 8, "feed_max_topic_share": 1.0}, settings=SETTINGS
        )

    def godot_picks() -> list[feeds.FeedItem]:
        return [item for item in build(sessions).items if "Godot" in item.breakdown.tags]

    # No limit: after the pins and the loved channel's two, the boost puts them next.
    assert len(godot_picks()) == 4
    with sessions.begin() as session:
        update_user_settings(session, {"feed_max_topic_share": 0.25}, settings=SETTINGS)

    capped = build(sessions)

    # ceil(0.25 * 8) = 2 of the 8; the unboosted channels take the other places.
    assert len(capped.items) == 8
    assert len([item for item in capped.items if "Godot" in item.breakdown.tags]) == 2


def test_build_feed_follows_the_environments_share(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add_followed_channels(session, 6, "Godot")

    settings = Settings(feed_size=8, feed_exploration_slots=0, feed_max_topic_share=0.25)
    feed = build(sessions, settings=settings)

    assert len([item for item in feed.items if "Godot" in item.breakdown.tags]) == 2


def test_discover_caps_a_topic_too(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        godot = [add_outside(session, letter, tags=["Godot"]) for letter in "ABCDEF"]
        plain = [add_outside(session, letter) for letter in "GHIJ"]
        tag = resolve_tag(session, "Godot")
        assert tag is not None
        subscribe_tag(session, tag, weight=0.5)
        update_user_settings(session, {"feed_max_topic_share": 0.5}, settings=SETTINGS)

    items = discover(sessions, size=6)

    # Half of six: three Godot videos, although all six outscore the rest.
    assert len(items) == 6
    assert len([item for item in items if item.video_id in godot]) == 3
    assert len([item for item in items if item.video_id in plain]) == 3


# Wildcards


def add_outside(
    session: Session,
    letter: str,
    *,
    source: str = RELATED,
    tags: Sequence[str] = (),
    embedding: Sequence[float] | None = None,
    published: str = "2026-10-10T00:00:00.000Z",
    days_ago: int = 0,
) -> str:
    """A video on a channel of its own that isn't subscribed (`UC` and 22 `letter`s), found
    by `source` `days_ago` days (and an hour) before `NOW`, with the given tags and
    embedding. Returns the video's id."""
    channel_id = "UC" + letter * 22
    video_id = vid(channel_id, 0)
    session.execute(
        text("INSERT INTO channels (id, title) VALUES (:id, :title)"),
        {"id": channel_id, "title": f"Outside {letter}"},
    )
    session.execute(
        text(
            "INSERT INTO videos (id, channel_id, title, published_at) "
            "VALUES (:id, :channel, 'Outside video', :published)"
        ),
        {"id": video_id, "channel": channel_id, "published": published},
    )
    record(session, [video_id], source=source, now=NOW - timedelta(days=days_ago, hours=1))
    if tags:
        proposals = [ProposedTag(tag, 0.9) for tag in tags]
        set_llm_tags(session, video_id, proposals, prompt_version=1)
    if embedding is not None:
        store_embedding(session, video_id, list(embedding))
    return video_id


def wildcards(
    sessions: sessionmaker[Session],
    size: int = 3,
    now: datetime = NOW,
    exclude: Collection[str] = (),
) -> list[feeds.DiscoveryItem]:
    with sessions() as session:
        return feeds.wildcards(session, size=size, exclude=exclude, settings=SETTINGS, now=now)


def test_wildcards_are_one_video_per_channel_from_outside_the_subscriptions(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        found = [
            add_outside(session, "A", source=RELATED),
            add_outside(session, "B", source=CHANNEL_GRAPH),
            add_outside(session, "C", source=SAVED_SEARCH),
            add_outside(session, "D", source=RELATED),
        ]
        # A second video of a channel in the pool isn't a second wildcard.
        session.execute(
            text("INSERT INTO videos (id, channel_id, title) VALUES ('A0000000001', :c, 'More')"),
            {"c": "UC" + "A" * 22},
        )
        record(session, ["A0000000001"], source=RELATED, now=NOW - timedelta(hours=1))
        subscribed = add_outside(session, "S", source=RELATED)
        session.execute(
            text("INSERT INTO channel_prefs (channel_id) VALUES (:id)"), {"id": "UC" + "S" * 22}
        )

    everything = wildcards(sessions, size=10)
    three = wildcards(sessions)

    assert sorted(item.video_id for item in everything) == sorted([*found[:1], *found[1:]])
    assert subscribed not in {item.video_id for item in everything}
    assert len({item.channel_id for item in everything}) == len(everything)
    assert len(three) == 3
    for item in three:
        assert item.explanation == "Wildcard: outside the topics you follow"
        assert item.channel_subscribed is False
        assert item.source in {RELATED, CHANNEL_GRAPH, SAVED_SEARCH}
    assert wildcards(sessions, size=1) != []


def spoil_by_rating(session: Session, video_id: str) -> None:
    set_rating(session, video_id, 7)


def spoil_by_an_earlier_dismissal(session: Session, video_id: str) -> None:
    earlier = feeds.build_feed(
        session, feed_date=date(2026, 10, 1), settings=SETTINGS, rng=random.Random(0), now=NOW
    )
    [item] = [item for item in earlier.items if item.video_id == video_id]
    feeds.dismiss_feed_item(session, item.id)


def spoil_by_todays_feed(session: Session, video_id: str) -> None:
    feeds.build_feed(session, feed_date=TODAY, settings=SETTINGS, rng=random.Random(0), now=NOW)


def spoil_by_subscribing(session: Session, video_id: str) -> None:
    session.execute(
        text("INSERT INTO channel_prefs (channel_id) VALUES ('UC' || :c)"), {"c": video_id[0] * 22}
    )


def hide_the_channel(kind: channel_hides.HideKind) -> Callable[[Session, str], None]:
    def spoil(session: Session, video_id: str) -> None:
        assert channel_hides.hide(session, "UC" + video_id[0] * 22, kind) is not None

    return spoil


def spoil_by_following_its_tag(session: Session, video_id: str) -> None:
    set_llm_tags(session, video_id, [ProposedTag("Rust", 0.9)], prompt_version=1)
    tag = resolve_tag(session, "Rust")
    assert tag is not None
    subscribe_tag(session, tag, weight=0.5)


def spoil_by_muting_its_tag(session: Session, video_id: str) -> None:
    set_llm_tags(session, video_id, [ProposedTag("Rust", 0.9)], prompt_version=1)
    tag = resolve_tag(session, "Rust")
    assert tag is not None
    subscribe_tag(session, tag, weight=-0.5)


def spoil_by_being_a_tag_search_result(session: Session, video_id: str) -> None:
    session.execute(
        text("UPDATE candidates SET source = 'tag' WHERE video_id = :id"), {"id": video_id}
    )


def spoil_by_being_a_short(session: Session, video_id: str) -> None:
    session.execute(text("UPDATE videos SET is_short = 1 WHERE id = :id"), {"id": video_id})


def spoil_by_being_live(session: Session, video_id: str) -> None:
    session.execute(
        text("UPDATE videos SET live_status = 'is_live' WHERE id = :id"), {"id": video_id}
    )


def spoil_by_being_too_long(session: Session, video_id: str) -> None:
    session.execute(
        text("UPDATE videos SET duration_seconds = 1200 WHERE id = :id"), {"id": video_id}
    )
    update_user_settings(session, {"feed_max_duration_seconds": 600}, settings=SETTINGS)


def spoil_by_a_keyword_mute(session: Session, video_id: str) -> None:
    add_keyword_mute(session, "outside")


@pytest.mark.parametrize(
    "spoil",
    [
        spoil_by_rating,
        spoil_by_an_earlier_dismissal,
        spoil_by_todays_feed,
        spoil_by_subscribing,
        hide_the_channel("dismissed"),
        hide_the_channel("blocked"),
        spoil_by_following_its_tag,
        spoil_by_muting_its_tag,
        spoil_by_being_a_tag_search_result,
        spoil_by_being_a_short,
        spoil_by_being_live,
        spoil_by_being_too_long,
        spoil_by_a_keyword_mute,
    ],
)
def test_a_wildcard_must_pass_every_rule(
    sessions: sessionmaker[Session], spoil: Callable[[Session, str], None]
) -> None:
    with sessions.begin() as session:
        video_id = add_outside(session, "K")
    assert [item.video_id for item in wildcards(sessions)] == [video_id]  # as it stands

    with sessions.begin() as session:
        spoil(session, video_id)

    assert wildcards(sessions) == []


def test_wildcards_look_further_back_than_the_feed(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        fresh = add_outside(session, "A")
        older = add_outside(session, "B", days_ago=20)
        ancient = add_outside(session, "C", days_ago=feeds.WILDCARD_DAYS + 10)
    in_feed = {item.video_id for item in build(sessions).items}

    picked = {item.video_id for item in wildcards(sessions, size=5)}

    # The feed's window is a week: it has the fresh one only, and "Show more" can't find
    # the older ones. The wildcards are what lies beyond, up to a point.
    assert in_feed >= {fresh} and in_feed.isdisjoint({older, ancient})
    assert picked == {older}


def test_wildcards_leave_out_what_the_page_shows_already(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        shown = [add_outside(session, letter) for letter in "AB"]
        left = [add_outside(session, letter) for letter in "CDE"]

    picked = [item.video_id for item in wildcards(sessions, size=5, exclude=shown)]

    assert sorted(picked) == sorted(left)


def test_tags_that_are_not_followed_do_not_matter(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        followed = add_outside(session, "A", tags=["Rust"])
        other = add_outside(session, "B", tags=["Birds", "Owls"])
        tag = resolve_tag(session, "Rust")
        assert tag is not None
        subscribe_tag(session, tag, weight=0.5)

    assert [item.video_id for item in wildcards(sessions)] == [other]
    assert followed not in {item.video_id for item in wildcards(sessions)}


def test_wildcards_prefer_videos_with_tags_and_embeddings(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(feeds, "WILDCARD_POOL", 3)
    with sessions.begin() as session:
        known = [
            add_outside(session, letter, tags=["Birds"], embedding=unit(n))
            for n, letter in enumerate("ABC")
        ]
        add_outside(session, "D", tags=["Birds"])
        add_outside(session, "E", tags=["Birds"])
        add_outside(session, "F", embedding=unit(5))
        add_outside(session, "G")
        add_outside(session, "H", published="2026-10-11T00:00:00.000Z")

    picked = [item.video_id for item in wildcards(sessions, size=3)]

    assert sorted(picked) == sorted(known)


def test_wildcards_draw_from_the_videos_most_like_what_i_rated_well(
    sessions: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(feeds, "WILDCARD_POOL", 2)
    liked = vid(PLAIN, 40)
    with sessions.begin() as session:
        session.execute(text("DELETE FROM candidates"))
        add_videos(session, PLAIN, range(40, 41), seen=NOW - timedelta(days=60))  # old
        set_rating(session, liked, 9)
        store_embedding(session, liked, unit(0))
        near = add_outside(session, "A", tags=["Birds"], embedding=unit(0))
        between = add_outside(
            session, "B", tags=["Birds"], embedding=[0.7 if i < 2 else 0.0 for i in range(384)]
        )
        for n, letter in enumerate("CDE"):
            add_outside(session, letter, tags=["Birds"], embedding=unit(n + 1))

    picks = wildcards(sessions, size=2)

    assert [item.video_id for item in picks] == [near, between]
    assert picks[0].breakdown.similarity > picks[1].breakdown.similarity > 0


def test_wildcards_stay_the_same_all_day_and_change_with_the_day(
    sessions: sessionmaker[Session],
) -> None:
    with sessions.begin() as session:
        update_user_settings(session, {"timezone": "UTC"}, settings=SETTINGS)
        for n, letter in enumerate("ABCDEFGHIJKL"):
            add_outside(session, letter, published=f"2026-10-{n + 1:02d}T00:00:00.000Z")

    def ids(now: datetime) -> list[str]:
        return [item.video_id for item in wildcards(sessions, now=now)]

    morning, evening = ids(NOW), ids(NOW + timedelta(hours=10))
    days = {tuple(ids(NOW + timedelta(days=d))) for d in range(6)}

    assert morning == evening and len(morning) == 3
    assert len(days) > 1


def test_wildcards_with_nothing_to_pick(tmp_path: Path) -> None:
    factory = open_database(tmp_path / "homefeed.sqlite")
    with factory() as session:
        assert feeds.wildcards(session, settings=SETTINGS, now=NOW) == []


# User settings (stored values over SETTINGS)


def test_build_feed_uses_the_stored_user_settings(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        update_user_settings(session, {"feed_size": 3}, settings=SETTINGS)

    assert len(build(sessions).items) == 3

    with sessions.begin() as session:
        update_user_settings(session, {}, reset=["feed_size"], settings=SETTINGS)
    assert len(build(sessions).items) == 6  # back to SETTINGS' 15: all there is


def test_build_feed_dates_the_feed_in_the_user_time_zone(sessions: sessionmaker[Session]) -> None:
    # 06:00 UTC on the 12th is still the 11th in Honolulu.
    with sessions.begin() as session:
        update_user_settings(session, {"timezone": "Pacific/Honolulu"}, settings=SETTINGS)

    assert build(sessions).date == date(2026, 10, 11)


def test_local_today_in_a_time_zone() -> None:
    assert feeds.local_today(NOW, ZoneInfo("Pacific/Honolulu")) == date(2026, 10, 11)
    assert feeds.local_today(NOW, ZoneInfo("Asia/Tokyo")) == date(2026, 10, 12)
    assert feeds.local_today(NOW) == NOW.astimezone().date()  # the system's
