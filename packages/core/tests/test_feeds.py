import json
import math
import random
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import feeds
from homefeed_core.candidates import SUBSCRIPTION, record
from homefeed_core.composer import ChannelRatings
from homefeed_core.config import Settings
from homefeed_core.curation import add_keyword_mute, add_topic, subscribe_tag
from homefeed_core.db import open_database
from homefeed_core.embeddings import EMBEDDING_DIMENSIONS, StubEmbeddingProvider, store_embedding
from homefeed_core.enricher import Enricher, enrich_candidates, get_features
from homefeed_core.gateway.fake import FakeGateway, make_channel, make_video
from homefeed_core.model_features import FEATURE_NAMES
from homefeed_core.ranker import SIMILARITY_WEIGHT
from homefeed_core.ranking_models import RidgeModel, activate, record_version, save_model
from homefeed_core.ratings import set_rating
from homefeed_core.tags import ProposedTag, remove_video_tag, resolve_tag, set_llm_tags
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
            "topics",
            "final",
            "similarity_features",
        }
        assert feeds.get_feed(session, TODAY) == feed


def test_build_feed_stores_exploration_slots(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add_videos(session, LOVED, range(4, 10))
        scores = [7.8, 5.7, 4.7, 9.4, 1.6]  # 5 ratings: not explored
        for n, score in enumerate(scores):
            set_rating(session, vid(LOVED, n), score)
        set_rating(session, vid(PLAIN, 0), 3.2)
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


def test_watched_and_dismissed_are_left_out(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        set_rating(session, vid(LOVED, 3), 6.3)
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
        set_rating(session, rated.video_id, 7.0)
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
            set_rating(session, vid(PLAIN, n), 6.3)
        version_id = install_model(session, tmp_path)

    feed = build(sessions, settings=SETTINGS.model_copy(update={"data_dir": tmp_path}))

    assert feed.model_version == str(version_id)
    assert feed.items
    for item in feed.items:
        b = item.breakdown
        assert b.alpha == pytest.approx(5 / 55)
        assert b.model == pytest.approx(0.5 * b.channel + 0.1)
        parts = b.alpha * b.model + b.channel + b.similarity + sum(b.topics.values())
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
        set_rating(session, vid(PLAIN, 0), 6.3)
        install_model(session, tmp_path, path="ranking_models/missing.json")

    feed = build(sessions, settings=SETTINGS.model_copy(update={"data_dir": tmp_path}))

    assert feed.model_version is None
    assert all(item.breakdown.alpha == 0 and item.breakdown.model == 0 for item in feed.items)


def test_ratings_shape_channel_score(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        add_videos(session, PLAIN, range(10, 15))
        for n in range(10, 15):
            set_rating(session, vid(PLAIN, n), 10.0)

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


def test_topic_boosts_reorder_and_appear_in_the_breakdown(
    sessions: sessionmaker[Session],
) -> None:
    embedder = StubEmbeddingProvider(
        vectors={
            "woodworking": [1.0, 0.0, 0.0] + [0.0] * 381,
            "drama": [0.0, 1.0, 0.0] + [0.0] * 381,
        }
    )
    with sessions.begin() as session:
        session.execute(text("DELETE FROM candidates"))
        add_videos(session, PLAIN, range(50, 54))
        for n, vector in [(50, [0.0, 1.0, 0.0]), (51, [0.0, 0.0, 1.0]), (52, [1.0, 0.0, 0.0])]:
            store_embedding(session, vid(PLAIN, n), vector + [0.0] * 381)
        # 53 has no embedding (not enriched yet): no topic boosts.
        add_topic(session, embedder, name="Woodworking", description="woodworking", weight=0.6)
        add_topic(
            session,
            embedder,
            name="Drama",
            description="drama",
            weight=-1.0,
            decay=True,
            now=NOW - timedelta(days=30),
        )

    feed = build(sessions, settings=Settings(feed_size=15))

    plain = [item for item in feed.items if item.channel_id == PLAIN]
    by_id = {item.video_id: item for item in plain}
    # At most 2 per channel: the boosted one, then the newer unboosted.
    assert [item.video_id for item in plain] == [vid(PLAIN, 52), vid(PLAIN, 53)]
    assert by_id[vid(PLAIN, 52)].breakdown.topics == {"Woodworking": pytest.approx(0.6)}
    assert by_id[vid(PLAIN, 53)].breakdown.topics == {}
    assert by_id[vid(PLAIN, 52)].score == pytest.approx(0.6)
    with sessions() as session:
        stored = session.execute(
            text("SELECT breakdown FROM feed_items WHERE video_id = :id"), {"id": vid(PLAIN, 52)}
        ).scalar_one()
    assert json.loads(stored)["topics"] == {"Woodworking": pytest.approx(0.6)}


def test_tag_subscriptions_boost_tagged_videos_in_the_feed(
    sessions: sessionmaker[Session],
) -> None:
    embedder = StubEmbeddingProvider()
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
        subscribe_tag(session, embedder, rust, weight=0.5)

    feed = build(sessions, settings=Settings(feed_size=15))

    plain = {item.video_id: item for item in feed.items if item.channel_id == PLAIN}
    assert plain[vid(PLAIN, 50)].breakdown.topics == {"rust": pytest.approx(0.4)}
    assert all(item.breakdown.topics == {} for key, item in plain.items() if key != vid(PLAIN, 50))
    assert plain[vid(PLAIN, 50)].score == pytest.approx(0.4)


def test_decayed_suppression(sessions: sessionmaker[Session]) -> None:
    embedder = StubEmbeddingProvider(vectors={"drama": [1.0] + [0.0] * 383})
    with sessions.begin() as session:
        session.execute(text("DELETE FROM candidates"))
        add_videos(session, PLAIN, range(60, 61))
        store_embedding(session, vid(PLAIN, 60), [1.0] + [0.0] * 383)
        add_topic(
            session,
            embedder,
            name="Drama",
            description="drama",
            weight=-1.0,
            decay=True,
            now=NOW - timedelta(days=30),
        )

    [item] = build(sessions).items

    assert item.breakdown.topics == {"Drama": pytest.approx(-0.5)}
    assert item.score == pytest.approx(-0.5)


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
        set_rating(session, loved, 9.4)
        set_rating(session, hated, 1.9)
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
        set_rating(session, loved, 8.1)
        store_embedding(session, loved, unit(0))
        add_videos(session, PLAIN, range(41, 42))
        store_embedding(session, vid(PLAIN, 41), unit(0))

    feed = build(sessions)

    assert [item.explanation for item in feed.items] == [
        "New from your subscriptions · similar to Video 40 (8.1)"
    ]
    with sessions.begin() as session:
        stored = session.execute(text("SELECT explanation FROM feed_items")).scalar_one()
    assert stored == feed.items[0].explanation
