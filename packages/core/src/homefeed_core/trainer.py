"""Training the ranking model on the user's ratings (PLAN.md section 7, "Labels" and
"Training and promotion"). The worker runs `run_nightly_training` once a day.

Dataset (`build_dataset`), one example per video:
- Explicit rating: its value (-1 to 1) at weight 1.0, dated when the score last changed.
- Dismissed from a feed (and not rated): value -0.5 at weight 0.3, dated at the first
  dismissal.
- Abandoned within 60 seconds (and neither rated nor dismissed): value -0.5 at weight
  0.2, dated at its last watch event.
Rated videos ignore implicit signals. Videos ever shown as a pinned feed item are left
out (pins are shown whatever their score). A rating of a video shown in an exploration
slot is reweighted by the inverse of its selection probability, clipped to
`EXPLORATION_WEIGHT_CLIP` (the latest exploration appearance counts). Every weight is
then decayed by `0.5 ** (age_days / 180)`. Videos without stored metadata can't be
featurized and are skipped.

Features are those the ranker has at inference (see homefeed_core.model_features),
including the video's LLM tags of the current prompt version when it has them,
computed as of the label's time: a video's similarity to the top-tier and bottom-tier
sets and its channel score only use ratings given before it. So a label never leaks
into its own features (a video is not similar to itself, nor does its rating move its
channel score), and examples look like candidates did when they were shown.

Training (`train`): the newest `HOLDOUT_FRACTION` (20%) of explicit ratings by time are
held out; the model is fit on the earlier examples (implicit ones dated up to the
holdout's start) and scored on the holdout (Spearman correlation and MAE). The stored
model is then refit on every example, so the newest ratings count too. LightGBM is used
from `LIGHTGBM_MIN_RATINGS` explicit ratings, weighted ridge regression below that; no
model is trained below `MIN_EXPLICIT_RATINGS`.

Promotion: every trained model is recorded in `model_versions`; it becomes the active
model unless its holdout Spearman is worse than the active model's recorded one by more
than `PROMOTION_TOLERANCE` (0.02). An undefined Spearman counts as 0. The newest
`KEEP_VERSIONS` (10) versions are kept, plus the active one.
"""

import logging
import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.stats import rankdata
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from homefeed_core import watch_events
from homefeed_core.config import Settings, get_settings
from homefeed_core.curation import DEFAULT_PRIOR, Prior
from homefeed_core.db import get_session_factory
from homefeed_core.embeddings import Embedding, get_embeddings
from homefeed_core.llm_tags import get_scores
from homefeed_core.model_features import ModelInput, feature_matrix, upload_age_days
from homefeed_core.ranker import SimilarityFeatures, TierSimilarity, channel_score
from homefeed_core.ranking_models import (
    KEEP_VERSIONS,
    LightGBMModel,
    ModelKind,
    ModelVersion,
    RankingModel,
    RidgeModel,
    activate,
    delete_model_file,
    get_active_version,
    prune_versions,
    record_version,
    save_model,
)
from homefeed_core.ratings import list_ratings
from homefeed_core.scores import is_bottom_tier, is_top_tier

logger = logging.getLogger(__name__)

EXPLICIT_WEIGHT = 1.0
DISMISSED_VALUE = -0.5
DISMISSED_WEIGHT = 0.3
ABANDONED_VALUE = -0.5
ABANDONED_WEIGHT = 0.2
# Training weight halves every this many days since the label was given.
HALF_LIFE_DAYS = 180
# Upper bound of an exploration rating's inverse-propensity factor.
EXPLORATION_WEIGHT_CLIP = 10.0
# Share of explicit ratings (the newest) held out for evaluation.
HOLDOUT_FRACTION = 0.2
# Below this many explicit ratings no model is trained.
MIN_EXPLICIT_RATINGS = 20
# From this many explicit ratings LightGBM is used; below, ridge regression.
LIGHTGBM_MIN_RATINGS = 200
# L2 penalty of the ridge fallback (features are standardized).
RIDGE_L2 = 10.0
# A new model is promoted unless its Spearman is lower than the active one's by more.
PROMOTION_TOLERANCE = 0.02


class Signal(StrEnum):
    EXPLICIT = "explicit"
    DISMISSED = "dismissed"
    ABANDONED = "abandoned"


@dataclass(frozen=True)
class Example:
    video_id: str
    signal: Signal
    value: float  # the label, a rating value in [-1, 1]
    weight: float  # signal weight x exploration reweighting x time decay
    at: datetime  # when the label was given
    input: ModelInput


@dataclass(frozen=True)
class Evaluation:
    spearman: float | None  # None when undefined (constant labels or predictions)
    mae: float


@dataclass(frozen=True)
class TrainResult:
    version: ModelVersion
    promoted: bool
    previous_active: ModelVersion | None
    # Versions pruned from `model_versions`; delete their files after committing.
    pruned: list[ModelVersion] = field(default_factory=list)


def decay(age_days: float) -> float:
    """Time-decay factor of a label `age_days` old: `0.5 ** (age_days / 180)`."""
    return 0.5 ** (max(0.0, age_days) / HALF_LIFE_DAYS)


def exploration_factor(selection_probability: float) -> float:
    """Inverse-propensity factor of an exploration rating, clipped to
    [1, EXPLORATION_WEIGHT_CLIP]."""
    if selection_probability <= 0:
        return EXPLORATION_WEIGHT_CLIP
    return min(EXPLORATION_WEIGHT_CLIP, max(1.0, 1.0 / selection_probability))


def should_promote(
    new_spearman: float | None,
    active_spearman: float | None,
    *,
    tolerance: float = PROMOTION_TOLERANCE,
) -> bool:
    """Promote unless the new Spearman is worse than the active one by more than
    `tolerance`. Undefined (None) counts as 0."""
    return (new_spearman or 0.0) >= (active_spearman or 0.0) - tolerance - 1e-12


# Dataset


def build_dataset(session: Session, *, now: datetime | None = None) -> list[Example]:
    """Every labeled video as a training example (see the module docstring), oldest
    label first."""
    now = now or datetime.now(UTC)
    ratings = {rating.video_id: rating for rating in list_ratings(session)}
    pinned = set(
        session.execute(
            text("SELECT DISTINCT video_id FROM feed_items WHERE is_pinned = 1")
        ).scalars()
    )
    dismissed: dict[str, str] = {
        video_id: at
        for video_id, at in session.execute(
            text(
                """
                SELECT video_id, min(dismissed_at) FROM feed_items
                WHERE dismissed_at IS NOT NULL GROUP BY video_id
                """
            )
        )
    }
    abandoned = watch_events.abandoned_early_at(session)

    videos = _load_videos(session, ratings.keys() | dismissed.keys() | abandoned.keys())
    labels: dict[str, tuple[Signal, float, float, datetime]] = {}
    for video_id in videos.keys() - pinned:
        if (rating := ratings.get(video_id)) is not None:
            labels[video_id] = (
                Signal.EXPLICIT,
                rating.value,
                EXPLICIT_WEIGHT,
                _parse(rating.updated_at),
            )
        elif video_id in dismissed:
            labels[video_id] = (
                Signal.DISMISSED,
                DISMISSED_VALUE,
                DISMISSED_WEIGHT,
                _parse(dismissed[video_id]),
            )
        else:
            labels[video_id] = (
                Signal.ABANDONED,
                ABANDONED_VALUE,
                ABANDONED_WEIGHT,
                _parse(abandoned[video_id]),
            )
    if not labels:
        return []

    # Every rating, with when it was given, for the as-of features.
    rated = [
        (rating, _parse(rating.updated_at), videos.get(rating.video_id))
        for rating in ratings.values()
    ]
    exploration = _exploration_probabilities(session)
    sources = _sources(session)
    priors: dict[str, Prior] = {
        channel_id: prior
        for channel_id, prior in session.execute(
            text("SELECT channel_id, prior FROM channel_prefs")
        )
    }
    channel_ratings: defaultdict[str, list[tuple[datetime, float]]] = defaultdict(list)
    for rating, at, video in rated:
        if video is not None:
            channel_ratings[video[0]].append((at, rating.value))

    embeddings = get_embeddings(session, labels.keys() | ratings.keys())
    tags = get_scores(session, sorted(labels))
    label_times = {video_id: label[3] for video_id, label in labels.items()}
    similarities = _as_of_similarities(
        {v: (embeddings[v], label_times[v]) for v in labels if v in embeddings},
        top={
            r.video_id: (embeddings[r.video_id], at)
            for r, at, _ in rated
            if is_top_tier(r.score) and r.video_id in embeddings
        },
        bottom={
            r.video_id: (embeddings[r.video_id], at)
            for r, at, _ in rated
            if is_bottom_tier(r.score) and r.video_id in embeddings
        },
    )

    examples: list[Example] = []
    for video_id, (signal, value, weight, at) in labels.items():
        if signal is Signal.EXPLICIT and video_id in exploration:
            weight *= exploration_factor(exploration[video_id])
        channel_id, duration, published_at = videos[video_id]
        earlier = [v for rated_at, v in channel_ratings[channel_id] if rated_at < at]
        examples.append(
            Example(
                video_id=video_id,
                signal=signal,
                value=value,
                weight=weight * decay((now - at).total_seconds() / 86400),
                at=at,
                input=ModelInput(
                    video_id=video_id,
                    similarity=similarities.get(video_id),
                    embedding=embeddings.get(video_id),
                    duration_seconds=duration,
                    upload_age_days=upload_age_days(published_at, at),
                    source=sources.get(video_id),
                    channel_score=channel_score(priors.get(channel_id, DEFAULT_PRIOR), earlier),
                    tags=tags.get(video_id),
                ),
            )
        )
    examples.sort(key=lambda example: (example.at, example.video_id))
    return examples


def _load_videos(
    session: Session, video_ids: set[str]
) -> dict[str, tuple[str, int | None, str | None]]:
    """Channel id, duration and publish time of the stored videos among `video_ids`."""
    if not video_ids:
        return {}
    rows = session.execute(
        text(
            "SELECT id, channel_id, duration_seconds, published_at FROM videos WHERE id IN :ids"
        ).bindparams(bindparam("ids", expanding=True)),
        {"ids": sorted(video_ids)},
    )
    return {row[0]: (row[1], row[2], row[3]) for row in rows}


def _exploration_probabilities(session: Session) -> dict[str, float]:
    """Selection probability of each video's latest exploration appearance."""
    rows = session.execute(
        text(
            """
            SELECT i.video_id, i.selection_probability
            FROM feed_items AS i JOIN feeds AS f ON f.id = i.feed_id
            WHERE i.is_exploration = 1 AND i.selection_probability IS NOT NULL
            ORDER BY f.created_at, f.id
            """
        )
    )
    return {video_id: probability for video_id, probability in rows}


def _sources(session: Session) -> dict[str, str]:
    """Each video's candidate source: as of its latest feed appearance, else the first
    source that found it."""
    sources: dict[str, str] = {}
    for video_id, source in session.execute(
        text("SELECT video_id, source FROM candidates ORDER BY first_seen_at DESC, source DESC")
    ):
        sources[video_id] = source
    for video_id, source in session.execute(
        text(
            """
            SELECT i.video_id, i.source
            FROM feed_items AS i JOIN feeds AS f ON f.id = i.feed_id
            ORDER BY f.created_at, f.id
            """
        )
    ):
        sources[video_id] = source
    return sources


def _as_of_similarities(
    videos: Mapping[str, tuple[Embedding, datetime]],
    *,
    top: Mapping[str, tuple[Embedding, datetime]],
    bottom: Mapping[str, tuple[Embedding, datetime]],
) -> dict[str, SimilarityFeatures]:
    """Similarity features of each video (embedding, label time) to the tier-set videos
    (embedding, rating time) rated before its label time."""
    if not videos:
        return {}
    ids = list(videos)
    units = _unit_rows([videos[v][0] for v in ids])
    times = [videos[v][1] for v in ids]
    top_sims = _tier_similarities(units, times, top)
    bottom_sims = _tier_similarities(units, times, bottom)
    return {
        video_id: SimilarityFeatures(top_tier=top_sims[i], bottom_tier=bottom_sims[i])
        for i, video_id in enumerate(ids)
    }


def _tier_similarities(
    units: NDArray[np.float64],
    times: Sequence[datetime],
    tier: Mapping[str, tuple[Embedding, datetime]],
) -> list[TierSimilarity | None]:
    if not tier:
        return [None] * len(times)
    tier_ids = list(tier)
    similarities = units @ _unit_rows([tier[v][0] for v in tier_ids]).T
    tier_times = np.array([tier[v][1].timestamp() for v in tier_ids])
    result: list[TierSimilarity | None] = []
    for i, at in enumerate(times):
        earlier = np.flatnonzero(tier_times < at.timestamp())
        if len(earlier) == 0:
            result.append(None)
            continue
        row = similarities[i]
        nearest = int(earlier[np.argmax(row[earlier])])
        result.append(
            TierSimilarity(
                max=float(row[nearest]),
                mean=float(row[earlier].mean()),
                nearest_video_id=tier_ids[nearest],
            )
        )
    return result


def _unit_rows(vectors: Sequence[Embedding]) -> NDArray[np.float64]:
    matrix = np.array(vectors, dtype=np.float64)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return matrix / np.where(norms == 0, 1.0, norms)


def _parse(timestamp: str) -> datetime:
    parsed = datetime.fromisoformat(timestamp)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# Fitting and evaluation


def split_holdout(
    examples: Sequence[Example], *, fraction: float = HOLDOUT_FRACTION
) -> tuple[list[Example], list[Example]]:
    """(train, holdout): the holdout is the newest `fraction` of explicit examples (at
    least one); training gets the other examples given up to the holdout's start."""
    explicit = sorted(
        (e for e in examples if e.signal is Signal.EXPLICIT), key=lambda e: (e.at, e.video_id)
    )
    if not explicit:
        return list(examples), []
    holdout = explicit[-max(1, math.ceil(len(explicit) * fraction)) :]
    held = {example.video_id for example in holdout}
    start = holdout[0].at
    train = [e for e in examples if e.video_id not in held and e.at <= start]
    return train, holdout


def model_kind(n_explicit: int, *, lightgbm_min_ratings: int = LIGHTGBM_MIN_RATINGS) -> ModelKind:
    """LightGBM once there are enough explicit ratings, ridge regression before."""
    return "lightgbm" if n_explicit >= lightgbm_min_ratings else "ridge"


def fit(examples: Sequence[Example], kind: ModelKind) -> RankingModel:
    """Fit a model of `kind` to `examples` (values weighted by their weights)."""
    if not examples:
        raise ValueError("Cannot fit a model without examples")
    features = feature_matrix([example.input for example in examples])
    labels = np.array([example.value for example in examples], dtype=np.float64)
    weights = np.array([example.weight for example in examples], dtype=np.float64)
    if kind == "lightgbm":
        return LightGBMModel.fit(features, labels, weights)
    return RidgeModel.fit(features, labels, weights, l2=RIDGE_L2)


def evaluate(model: RankingModel, examples: Sequence[Example]) -> Evaluation:
    """Spearman correlation and mean absolute error of the model's predictions."""
    if not examples:
        raise ValueError("Cannot evaluate on no examples")
    labels = np.array([example.value for example in examples], dtype=np.float64)
    predictions = model.predict_matrix(feature_matrix([example.input for example in examples]))
    return Evaluation(
        spearman=spearman(labels, predictions),
        mae=float(np.mean(np.abs(labels - predictions))),
    )


def spearman(a: NDArray[np.float64], b: NDArray[np.float64]) -> float | None:
    """Spearman rank correlation (ties get average ranks); None if either side is
    constant or there are fewer than 2 values."""
    if len(a) < 2 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return None
    ranks_a = np.asarray(rankdata(a), dtype=np.float64)
    ranks_b = np.asarray(rankdata(b), dtype=np.float64)
    value = float(np.corrcoef(ranks_a, ranks_b)[0, 1])
    return max(-1.0, min(1.0, value)) if math.isfinite(value) else None


# Training and promotion


def train(
    session: Session,
    *,
    data_dir: Path | None = None,
    now: datetime | None = None,
    lightgbm_min_ratings: int = LIGHTGBM_MIN_RATINGS,
    min_explicit_ratings: int = MIN_EXPLICIT_RATINGS,
    keep: int = KEEP_VERSIONS,
) -> TrainResult | None:
    """Train, evaluate and record a model, promote it if it is not worse than the
    active one, and prune old versions. None when there are too few explicit ratings.

    The model file is written to `data_dir` right away; the caller commits, then
    deletes the files of `TrainResult.pruned`."""
    now = now or datetime.now(UTC)
    examples = build_dataset(session, now=now)
    n_explicit = sum(1 for e in examples if e.signal is Signal.EXPLICIT)
    if n_explicit < min_explicit_ratings:
        logger.info("Not training: %d explicit ratings (need %d)", n_explicit, min_explicit_ratings)
        return None
    train_set, holdout = split_holdout(examples)
    kind = model_kind(n_explicit, lightgbm_min_ratings=lightgbm_min_ratings)
    evaluation = evaluate(fit(train_set, kind), holdout)
    model = fit(examples, kind)

    path = save_model(model, data_dir)
    try:
        active = get_active_version(session)
        promote = (
            active is None
            or not active.compatible
            or should_promote(evaluation.spearman, active.spearman)
        )
        counts = {signal: 0 for signal in Signal}
        for example in examples:
            counts[example.signal] += 1
        metrics: dict[str, Any] = {
            "spearman": evaluation.spearman,
            "mae": evaluation.mae,
            "n_examples": len(examples),
            "n_explicit": counts[Signal.EXPLICIT],
            "n_dismissed": counts[Signal.DISMISSED],
            "n_abandoned": counts[Signal.ABANDONED],
            "n_train": len(train_set),
            "n_holdout": len(holdout),
            "holdout_start": holdout[0].at.isoformat(),
            "active_version": active.id if active else None,
            "active_spearman": active.spearman if active else None,
            "promoted": promote,
        }
        version = record_version(
            session,
            path=path,
            kind=kind,
            spearman=evaluation.spearman,
            mae=evaluation.mae,
            metrics=metrics,
            now=now,
        )
        if promote:
            promoted = activate(session, version.id, now=now)
            assert promoted is not None
            version = promoted
        pruned = prune_versions(session, keep=keep)
    except BaseException:
        delete_model_file(path, data_dir)
        raise
    logger.info(
        "Trained model version %d (%s, %d examples): Spearman %s, MAE %.3f; %s",
        version.id,
        kind,
        len(examples),
        "undefined" if evaluation.spearman is None else f"{evaluation.spearman:.3f}",
        evaluation.mae,
        "promoted" if promote else f"kept active version {active.id if active else None}",
    )
    return TrainResult(version=version, promoted=promote, previous_active=active, pruned=pruned)


def run_nightly_training(
    *,
    sessions: sessionmaker[Session] | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> TrainResult | None:
    """Train in one transaction, then delete the files of pruned versions."""
    sessions = sessions or get_session_factory()
    settings = settings or get_settings()
    with sessions.begin() as session:
        result = train(session, data_dir=settings.data_dir, now=now)
    if result is not None:
        for version in result.pruned:
            delete_model_file(version.path, settings.data_dir)
    return result
