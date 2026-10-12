"""The ranking model's inputs (PLAN.md section 7, "Features"), shared by training and
inference so both build exactly the same feature matrix.

A `ModelInput` describes one video at one moment: its similarity to the rated top-tier
and bottom-tier sets, its embedding, duration, upload age, candidate source and channel
score. `feature_matrix` turns inputs into rows of `FEATURE_NAMES`, with NaN for unknown
values (LightGBM handles them natively; the ridge fallback imputes them).

Inference (Milestone 3, the ranker) builds inputs from what `rank` already has:

    ModelInput.for_candidate(candidate, similarity, embedding, channel_score, now=now)

Changing the features (names, order or meaning) must bump `FEATURE_VERSION`: stored
models record the version they were trained with and refuse to load under another.
LLM tags join the features once the enricher produces them.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np
from numpy.typing import NDArray

from homefeed_core.candidates import RELATED, SUBSCRIPTION
from homefeed_core.embeddings import EMBEDDING_DIMENSIONS, Embedding
from homefeed_core.ranker import RankCandidate, SimilarityFeatures

FEATURE_VERSION = 1

# Candidate sources with a one-hot column each; any other source counts as "other".
SOURCES = (SUBSCRIPTION, RELATED)

_BASE_FEATURES = (
    "top_tier_max",
    "top_tier_mean",
    "bottom_tier_max",
    "bottom_tier_mean",
    "has_embedding",
    "log_duration",
    "log_upload_age_days",
    "channel_score",
    *(f"source_{source}" for source in SOURCES),
    "source_other",
)
EMBEDDING_FEATURES = tuple(f"embedding_{i}" for i in range(EMBEDDING_DIMENSIONS))
FEATURE_NAMES: tuple[str, ...] = _BASE_FEATURES + EMBEDDING_FEATURES


@dataclass(frozen=True)
class ModelInput:
    """What the model knows about a video when scoring it. `None` means unknown."""

    video_id: str
    similarity: SimilarityFeatures | None = None
    embedding: Embedding | None = None
    duration_seconds: float | None = None
    upload_age_days: float | None = None  # at the time it is scored (or was rated)
    source: str | None = None  # candidate source, e.g. "subscription"
    channel_score: float = 0.0

    @classmethod
    def for_candidate(
        cls,
        candidate: RankCandidate,
        similarity: SimilarityFeatures | None,
        embedding: Embedding | None,
        channel_score: float,
        *,
        now: datetime,
    ) -> "ModelInput":
        """The input for scoring a feed candidate at `now`."""
        return cls(
            video_id=candidate.video_id,
            similarity=similarity,
            embedding=embedding,
            duration_seconds=candidate.duration_seconds,
            upload_age_days=upload_age_days(candidate.published_at, now),
            source=candidate.source,
            channel_score=channel_score,
        )


def upload_age_days(published_at: str | None, at: datetime) -> float | None:
    """Days from `published_at` (ISO 8601) to `at`, at least 0; None if unknown."""
    if published_at is None:
        return None
    published = datetime.fromisoformat(published_at)
    return max(0.0, (at - published).total_seconds() / 86400)


def feature_row(model_input: ModelInput) -> list[float]:
    """One input as a row of `FEATURE_NAMES`, NaN where unknown."""
    nan = math.nan
    similarity = model_input.similarity
    top = similarity.top_tier if similarity else None
    bottom = similarity.bottom_tier if similarity else None
    duration = model_input.duration_seconds
    age = model_input.upload_age_days
    source = model_input.source
    row = [
        top.max if top else nan,
        top.mean if top else nan,
        bottom.max if bottom else nan,
        bottom.mean if bottom else nan,
        1.0 if model_input.embedding is not None else 0.0,
        math.log1p(duration) if duration is not None and duration >= 0 else nan,
        math.log1p(age) if age is not None else nan,
        model_input.channel_score,
        *(1.0 if source == known else 0.0 for known in SOURCES),
        0.0 if source in SOURCES else 1.0,
    ]
    embedding = model_input.embedding
    if embedding is None:
        row.extend([nan] * EMBEDDING_DIMENSIONS)
    else:
        if len(embedding) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Expected a {EMBEDDING_DIMENSIONS}-dimensional embedding, got {len(embedding)}"
            )
        row.extend(embedding)
    return row


def feature_matrix(inputs: Sequence[ModelInput]) -> NDArray[np.float64]:
    """Inputs as a `len(inputs) x len(FEATURE_NAMES)` matrix."""
    if not inputs:
        return np.empty((0, len(FEATURE_NAMES)))
    return np.array([feature_row(model_input) for model_input in inputs], dtype=np.float64)
