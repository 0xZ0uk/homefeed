import json
import math
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import trainer
from homefeed_core.config import Settings
from homefeed_core.db import open_database
from homefeed_core.embeddings import EMBEDDING_DIMENSIONS, store_embedding
from homefeed_core.feeds import load_rated_tiers
from homefeed_core.gateway.events import format_timestamp
from homefeed_core.llm_tags import LLMTags, store_tags
from homefeed_core.model_features import FEATURE_NAMES, FEATURE_VERSION, ModelInput
from homefeed_core.ranker import (
    ModelCandidate,
    RankCandidate,
    SimilarityFeatures,
    similarity_features,
)
from homefeed_core.ranking_models import (
    IncompatibleModelError,
    RankingModel,
    activate,
    get_active_version,
    list_model_versions,
    load_active_model,
    prune_versions,
    ranker_model,
    read_model,
    record_version,
)
from homefeed_core.scores import score_value, value_score
from homefeed_core.trainer import (
    Signal,
    build_dataset,
    decay,
    exploration_factor,
    run_nightly_training,
    should_promote,
    split_holdout,
    train,
)
from homefeed_core.watch_events import record_watch_event

NOW = datetime(2026, 10, 13, 3, 0, tzinfo=UTC)
CHANNEL = "UC" + "a" * 22
CHANNELS = ["UC" + c * 22 for c in "abcd"]


@pytest.fixture
def sessions(tmp_path: Path) -> Iterator[sessionmaker[Session]]:
    factory = open_database(tmp_path / "homefeed.sqlite")
    with factory.begin() as session:
        for channel_id in CHANNELS:
            session.execute(
                text("INSERT INTO channels (id, title) VALUES (:id, 'Channel')"), {"id": channel_id}
            )
            session.execute(
                text("INSERT INTO channel_prefs (channel_id) VALUES (:id)"), {"id": channel_id}
            )
    yield factory
    bind = factory.kw["bind"]
    assert isinstance(bind, Engine)
    bind.dispose()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", database_path=tmp_path / "homefeed.sqlite")


def add_video(
    session: Session,
    video_id: str,
    *,
    channel_id: str = CHANNEL,
    duration: int | None = 600,
    published: datetime = NOW - timedelta(days=400),
) -> None:
    session.execute(
        text(
            """
            INSERT INTO videos (id, channel_id, title, duration_seconds, published_at)
            VALUES (:id, :channel, :id, :duration, :published)
            """
        ),
        {
            "id": video_id,
            "channel": channel_id,
            "duration": duration,
            "published": format_timestamp(published),
        },
    )


def rate(session: Session, video_id: str, value: float, at: datetime) -> None:
    """Rate with the score nearest to `value`, at a given time."""
    score = value_score(value)
    session.execute(
        text(
            """
            INSERT INTO ratings (video_id, score, value, rated_at, updated_at)
            VALUES (:id, :score, :value, :at, :at)
            ON CONFLICT (video_id) DO UPDATE SET
                score = excluded.score, value = excluded.value, updated_at = excluded.updated_at
            """
        ),
        {"id": video_id, "score": score, "value": score_value(score), "at": format_timestamp(at)},
    )


def add_feed_item(
    session: Session,
    video_id: str,
    *,
    is_pinned: bool = False,
    is_exploration: bool = False,
    selection_probability: float | None = None,
    dismissed_at: datetime | None = None,
    source: str = "subscription",
    created_at: datetime = NOW - timedelta(days=1),
) -> None:
    feed_id = session.execute(
        text("INSERT INTO feeds (date, created_at) VALUES ('2026-10-12', :at) RETURNING id"),
        {"at": format_timestamp(created_at)},
    ).scalar_one()
    session.execute(
        text(
            """
            INSERT INTO feed_items (feed_id, video_id, position, source, score, breakdown,
                                    explanation, is_pinned, is_exploration,
                                    selection_probability, dismissed_at)
            VALUES (:feed, :video, 0, :source, 0, '{}', '', :pinned, :exploration,
                    :probability, :dismissed)
            """
        ),
        {
            "feed": feed_id,
            "video": video_id,
            "source": source,
            "pinned": int(is_pinned),
            "exploration": int(is_exploration),
            "probability": selection_probability,
            "dismissed": format_timestamp(dismissed_at) if dismissed_at else None,
        },
    )


def abandon(session: Session, video_id: str, at: datetime) -> None:
    record_watch_event(session, video_id, "play", 0.0, 600.0, at=format_timestamp(at))
    record_watch_event(session, video_id, "close", 30.0, 600.0, at=format_timestamp(at))


# Synthetic histories


def unit(vector: np.ndarray) -> list[float]:
    return (vector / np.linalg.norm(vector)).tolist()


def taste_axis(seed: int = 7) -> np.ndarray:
    return np.array(unit(np.random.default_rng(seed).normal(size=EMBEDDING_DIMENSIONS)))


def synthetic_embedding(quality: float, rng: np.random.Generator) -> list[float]:
    """A video embedding whose component along the taste axis is the video's quality."""
    noise = rng.normal(size=EMBEDDING_DIMENSIONS) * (0.6 / math.sqrt(EMBEDDING_DIMENSIONS))
    return unit(quality * taste_axis() + noise)


def synthetic_history(
    sessions: sessionmaker[Session],
    n: int,
    *,
    seed: int = 0,
    learnable: bool = True,
    prefix: str = "v",
) -> None:
    """`n` rated videos over the last 300 days. With `learnable`, each rating follows
    the video's quality (its position along a taste axis in embedding space, plus a
    little noise); otherwise ratings are unrelated to the videos."""
    rng = np.random.default_rng(seed)
    with sessions.begin() as session:
        for i in range(n):
            video_id = f"{prefix}{i:09d}"[:11]
            quality = float(rng.uniform(-1, 1))
            add_video(session, video_id, channel_id=CHANNELS[i % len(CHANNELS)])
            store_embedding(session, video_id, synthetic_embedding(quality, rng))
            value = quality + rng.normal(0, 0.1) if learnable else rng.uniform(-1, 1)
            rate(session, video_id, value, NOW - timedelta(days=float(rng.uniform(0, 300))))


def relabel_with_noise(sessions: sessionmaker[Session], *, seed: int = 99) -> None:
    """Replace every rating's score with a random one, keeping its time."""
    rng = np.random.default_rng(seed)
    with sessions.begin() as session:
        for video_id in session.execute(text("SELECT video_id FROM ratings")).scalars().all():
            score = int(rng.integers(10, 101)) / 10
            session.execute(
                text("UPDATE ratings SET score = :score, value = :value WHERE video_id = :id"),
                {"id": video_id, "score": score, "value": score_value(score)},
            )


def train_now(
    sessions: sessionmaker[Session],
    settings: Settings,
    *,
    lightgbm_min_ratings: int = trainer.LIGHTGBM_MIN_RATINGS,
) -> trainer.TrainResult:
    with sessions.begin() as session:
        result = train(
            session, data_dir=settings.data_dir, now=NOW, lightgbm_min_ratings=lightgbm_min_ratings
        )
    assert result is not None
    return result


# Weights


def test_decay_halves_every_180_days() -> None:
    assert decay(0) == 1.0
    assert decay(180) == pytest.approx(0.5)
    assert decay(360) == pytest.approx(0.25)
    assert decay(-5) == 1.0  # labels from the future don't gain weight


def test_exploration_factor_is_the_clipped_inverse_probability() -> None:
    assert exploration_factor(1.0) == 1.0
    assert exploration_factor(0.25) == pytest.approx(4.0)
    assert exploration_factor(0.01) == 10.0
    assert exploration_factor(0.0) == 10.0


def test_promotion_tolerates_a_spearman_drop_of_up_to_002() -> None:
    assert should_promote(0.80, 0.70)
    assert should_promote(0.70, 0.70)
    assert should_promote(0.685, 0.70)
    assert should_promote(0.68, 0.70)
    assert not should_promote(0.67, 0.70)
    assert should_promote(None, None)
    assert not should_promote(None, 0.5)  # undefined counts as 0
    assert should_promote(0.1, None)


# Dataset


def test_dataset_labels_weights_and_exclusions(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        for video_id in ["rated", "old", "dismissed", "abandoned", "both", "pinrated", "pindis"]:
            add_video(session, video_id)
        for video_id in ["explore", "rareexplore", "abandoned2"]:
            add_video(session, video_id)
        rate(session, "rated", 1.0, NOW)
        rate(session, "old", -1.0, NOW - timedelta(days=180))
        add_feed_item(session, "dismissed", dismissed_at=NOW - timedelta(days=360))
        abandon(session, "abandoned", NOW)
        # Dismissed and abandoned: the dismissal (the stronger signal) counts.
        add_feed_item(session, "abandoned2", dismissed_at=NOW)
        abandon(session, "abandoned2", NOW)
        # Rated videos ignore implicit signals.
        rate(session, "both", 1.0, NOW)
        add_feed_item(session, "both", dismissed_at=NOW)
        abandon(session, "both", NOW)
        # Pinned items are left out, rated or dismissed.
        rate(session, "pinrated", 1.0, NOW)
        add_feed_item(session, "pinrated", is_pinned=True)
        add_feed_item(session, "pindis", is_pinned=True, dismissed_at=NOW)
        # Exploration ratings are reweighted by the latest appearance's probability.
        add_feed_item(
            session,
            "explore",
            is_exploration=True,
            selection_probability=0.9,
            created_at=NOW - timedelta(days=5),
        )
        add_feed_item(session, "explore", is_exploration=True, selection_probability=0.25)
        rate(session, "explore", 0.5, NOW)
        add_feed_item(session, "rareexplore", is_exploration=True, selection_probability=0.01)
        rate(session, "rareexplore", 0.5, NOW)
        # Rated without stored metadata: can't be featurized.
        rate(session, "unknown", 1.0, NOW)

    with sessions() as session:
        examples = {e.video_id: e for e in build_dataset(session, now=NOW)}

    assert set(examples) == {
        "rated",
        "old",
        "dismissed",
        "abandoned",
        "abandoned2",
        "both",
        "explore",
        "rareexplore",
    }
    labels = {v: (e.signal, e.value, e.weight) for v, e in examples.items()}
    assert labels["rated"] == (Signal.EXPLICIT, 1.0, 1.0)
    assert labels["old"][:2] == (Signal.EXPLICIT, -1.0)
    assert labels["old"][2] == pytest.approx(0.5)
    assert labels["dismissed"][:2] == (Signal.DISMISSED, -0.5)
    assert labels["dismissed"][2] == pytest.approx(0.3 * 0.25)
    assert labels["abandoned"] == (Signal.ABANDONED, -0.5, pytest.approx(0.2))
    assert labels["abandoned2"] == (Signal.DISMISSED, -0.5, pytest.approx(0.3))
    assert labels["both"] == (Signal.EXPLICIT, 1.0, 1.0)
    assert labels["explore"][2] == pytest.approx(4.0)
    assert labels["rareexplore"][2] == pytest.approx(10.0)


def test_dataset_features_only_use_earlier_ratings(sessions: sessionmaker[Session]) -> None:
    rng = np.random.default_rng(1)
    with sessions.begin() as session:
        session.execute(
            text("UPDATE channel_prefs SET prior = 'love' WHERE channel_id = :id"), {"id": CHANNEL}
        )
        for video_id, value, days_ago in [("bottom1", -1.0, 3), ("top2", 0.9, 2), ("top1", 1.0, 1)]:
            add_video(session, video_id)
            store_embedding(session, video_id, synthetic_embedding(value, rng))
            rate(session, video_id, value, NOW - timedelta(days=days_ago))
        add_video(session, "related", duration=3600)
        add_feed_item(session, "related", source="related", dismissed_at=NOW)

    with sessions() as session:
        examples = {e.video_id: e for e in build_dataset(session, now=NOW)}

    top1 = examples["top1"].input
    assert top1.similarity is not None and top1.similarity.top_tier is not None
    # Compared with the top-tier video rated before it, not with itself.
    assert top1.similarity.top_tier.nearest_video_id == "top2"
    assert top1.similarity.top_tier.max < 0.99
    assert top1.similarity.bottom_tier is not None
    assert top1.similarity.bottom_tier.nearest_video_id == "bottom1"
    # Nothing in the top tier was rated before top2.
    top2 = examples["top2"].input
    assert top2.similarity is not None and top2.similarity.top_tier is None
    assert examples["bottom1"].input.similarity == SimilarityFeatures(None, None)
    # Channel score from the earlier ratings: (0.9 + -1.0 + 0.8 * 5) / (2 + 5).
    top2_value = score_value(value_score(0.9))
    assert top1.channel_score == pytest.approx((top2_value - 1.0 + 4) / 7)
    assert examples["bottom1"].input.channel_score == pytest.approx(0.8)
    assert top1.upload_age_days == pytest.approx(399)
    assert top1.duration_seconds == 600

    related = examples["related"].input
    assert related.source == "related"
    assert related.embedding is None and related.similarity is None
    # All three ratings came before the dismissal.
    assert related.channel_score == pytest.approx((1.0 + top2_value - 1.0 + 4) / 8)


def test_holdout_is_the_newest_fifth_of_explicit_ratings(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        for day in range(10):
            add_video(session, f"r{day}")
            rate(session, f"r{day}", 0.5, NOW - timedelta(days=10 - day))
        add_video(session, "early")
        add_feed_item(session, "early", dismissed_at=NOW - timedelta(days=5))
        add_video(session, "late")
        add_feed_item(session, "late", dismissed_at=NOW)

    with sessions() as session:
        train_set, holdout = split_holdout(build_dataset(session, now=NOW))

    assert [e.video_id for e in holdout] == ["r8", "r9"]
    # Implicit labels from after the holdout starts are not trained on.
    assert {e.video_id for e in train_set} == {f"r{day}" for day in range(8)} | {"early"}


# Training and promotion


def test_trains_a_ridge_model_on_a_learnable_history(
    sessions: sessionmaker[Session], settings: Settings
) -> None:
    synthetic_history(sessions, 80)

    result = train_now(sessions, settings)

    version = result.version
    assert version.kind == "ridge"
    assert result.promoted and version.active and result.previous_active is None
    assert version.spearman is not None and version.spearman > 0.7
    assert 0 <= version.mae < 0.4
    assert version.metrics["n_explicit"] == 80
    assert version.metrics["n_holdout"] == 16
    assert version.metrics["spearman"] == version.spearman
    assert (settings.data_dir / version.path).is_file()
    with sessions() as session:
        stored = session.execute(
            text("SELECT spearman, mae, json_extract(metrics, '$.mae') FROM model_versions")
        ).one()
    assert stored == (version.spearman, version.mae, version.mae)


def test_trains_lightgbm_once_there_are_enough_ratings(
    sessions: sessionmaker[Session], settings: Settings
) -> None:
    synthetic_history(sessions, 300)

    result = train_now(sessions, settings, lightgbm_min_ratings=200)

    assert result.version.kind == "lightgbm"
    assert result.version.spearman is not None and result.version.spearman > 0.7


def test_dataset_features_include_llm_tags(sessions: sessionmaker[Session]) -> None:
    tags = LLMTags("crafts_diy", depth=0.9, clickbait=0.1, rage_bait=0.0)
    with sessions.begin() as session:
        add_video(session, "tagged00000")
        add_video(session, "untagged000")
        rate(session, "tagged00000", 0.5, NOW - timedelta(days=2))
        rate(session, "untagged000", 0.5, NOW - timedelta(days=1))
        store_tags(session, "tagged00000", tags, model="stub")
        examples = {example.video_id: example for example in build_dataset(session, now=NOW)}

    assert examples["tagged00000"].input.tags == tags
    assert examples["untagged000"].input.tags is None


def test_model_learns_from_llm_tags(sessions: sessionmaker[Session], settings: Settings) -> None:
    """Ratings that follow only the clickbait score: the trained model, used by the
    ranker, prefers a plainly titled video to a clickbait one."""
    rng = np.random.default_rng(3)
    with sessions.begin() as session:
        for i in range(60):
            video_id = f"t{i:010d}"
            clickbait = float(rng.uniform(0, 1))
            add_video(session, video_id, channel_id=CHANNELS[i % len(CHANNELS)])
            store_tags(session, video_id, LLMTags("other", 0.5, clickbait, 0.0), model="stub")
            rate(session, video_id, 0.8 - 1.6 * clickbait, NOW - timedelta(days=i + 1))
    train_now(sessions, settings)
    with sessions() as session:
        active = load_active_model(session, data_dir=settings.data_dir)
    assert active is not None

    def item(video_id: str, clickbait: float) -> ModelCandidate:
        return ModelCandidate(
            RankCandidate(video_id, CHANNEL, "subscription", duration_seconds=600),
            similarity=None,
            embedding=None,
            channel_score=0.0,
            tags=LLMTags("other", 0.5, clickbait, 0.0),
        )

    plain, bait = ranker_model(active.model, now=NOW)([item("plain", 0.05), item("bait", 0.95)])
    assert plain > bait


def test_active_model_ranks_unseen_videos_by_the_learned_taste(
    sessions: sessionmaker[Session], settings: Settings
) -> None:
    synthetic_history(sessions, 80)
    train_now(sessions, settings)
    rng = np.random.default_rng(5)

    with sessions() as session:
        active = load_active_model(session, data_dir=settings.data_dir)
        tiers = load_rated_tiers(session)
    assert active is not None and active.version.active

    def video(quality: float) -> ModelInput:
        embedding = tuple(synthetic_embedding(quality, rng))
        return ModelInput(
            video_id="new",
            similarity=similarity_features(embedding, tiers),
            embedding=embedding,
            duration_seconds=600,
            upload_age_days=1,
            source="subscription",
        )

    good, middling, bad = active.model.predict([video(0.9), video(0.0), video(-0.9)])
    assert good > middling > bad
    assert all(-1 <= score <= 1 for score in (good, middling, bad))


def test_a_worse_model_is_recorded_but_not_promoted(
    sessions: sessionmaker[Session], settings: Settings
) -> None:
    synthetic_history(sessions, 100)
    first = train_now(sessions, settings)
    assert first.promoted

    relabel_with_noise(sessions)
    second = train_now(sessions, settings)

    assert not second.promoted
    assert second.previous_active == first.version
    assert second.version.spearman is None or second.version.spearman < 0.5
    assert second.version.metrics["promoted"] is False
    assert second.version.metrics["active_spearman"] == first.version.spearman
    with sessions() as session:
        active = get_active_version(session)
        versions = list_model_versions(session)
    assert active is not None and active.id == first.version.id
    assert [v.id for v in versions] == [second.version.id, first.version.id]


def test_a_model_as_good_as_the_active_one_is_promoted(
    sessions: sessionmaker[Session], settings: Settings
) -> None:
    synthetic_history(sessions, 80)
    first = train_now(sessions, settings)
    second = train_now(sessions, settings)  # same data, same Spearman

    assert second.promoted
    with sessions() as session:
        active = get_active_version(session)
        old = list_model_versions(session)[1]
    assert active is not None and active.id == second.version.id
    assert old.id == first.version.id and not old.active


def test_not_enough_ratings_trains_nothing(
    sessions: sessionmaker[Session], settings: Settings
) -> None:
    synthetic_history(sessions, 19)

    with sessions.begin() as session:
        assert train(session, data_dir=settings.data_dir, now=NOW) is None
        assert list_model_versions(session) == []
    assert not (settings.data_dir / "ranking_models").exists()


def test_nightly_training_keeps_the_last_10_versions(
    sessions: sessionmaker[Session], settings: Settings
) -> None:
    synthetic_history(sessions, 30)

    results = [
        run_nightly_training(sessions=sessions, settings=settings, now=NOW) for _ in range(12)
    ]

    with sessions() as session:
        versions = list_model_versions(session)
    ids = [r.version.id for r in results if r is not None]
    assert [v.id for v in versions] == ids[::-1][:10]
    files = {p.name for p in (settings.data_dir / "ranking_models").iterdir()}
    assert files == {Path(v.path).name for v in versions}


def test_pruning_never_drops_the_active_version(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        ids = [
            record_version(
                session, path=f"m{i}.json", kind="ridge", spearman=0.5, mae=0.3, metrics={}
            ).id
            for i in range(5)
        ]
        activate(session, ids[0])
        pruned = prune_versions(session, keep=3)
        remaining = [v.id for v in list_model_versions(session)]

    assert [v.id for v in pruned] == [ids[1]]
    assert remaining == [ids[4], ids[3], ids[2], ids[0]]


# Model files and activation


def test_model_files_round_trip_and_refuse_other_features(
    sessions: sessionmaker[Session], settings: Settings
) -> None:
    synthetic_history(sessions, 40)
    version = train_now(sessions, settings).version
    path = settings.data_dir / version.path

    model = read_model(version.path, settings.data_dir)
    data = json.loads(path.read_text())
    assert data["feature_version"] == FEATURE_VERSION
    assert data["feature_names"] == list(FEATURE_NAMES)
    assert RankingModel.from_dict(model.to_dict()).to_dict() == model.to_dict()

    path.write_text(json.dumps({**data, "feature_version": FEATURE_VERSION + 1}))
    with pytest.raises(IncompatibleModelError):
        read_model(version.path, settings.data_dir)
    with sessions() as session:
        # The feed falls back to rules-only rather than failing.
        assert load_active_model(session, data_dir=settings.data_dir) is None


def test_activate_switches_the_active_version(sessions: sessionmaker[Session]) -> None:
    with sessions.begin() as session:
        a = record_version(session, path="a.json", kind="ridge", spearman=0.5, mae=0.3, metrics={})
        b = record_version(session, path="b.json", kind="ridge", spearman=0.6, mae=0.3, metrics={})
        activate(session, b.id, now=NOW)
        rolled_back = activate(session, a.id, now=NOW)
        assert activate(session, 999) is None
        session.execute(
            text("UPDATE model_versions SET feature_version = 0 WHERE id = :id"), {"id": b.id}
        )
        with pytest.raises(IncompatibleModelError):
            activate(session, b.id)

        active = get_active_version(session)
    assert rolled_back is not None and rolled_back.active
    assert rolled_back.activated_at == format_timestamp(NOW)
    assert active is not None and active.id == a.id
