"""Scoring feed candidates (PLAN.md section 7). Pure: no I/O, everything is passed in.

`rank` drops candidates that fail a hard filter, scores the rest and returns them best
first. Each score comes with a breakdown whose parts sum to it:

    final = alpha * model + channel + similarity + sum(topics)

`alpha = n / (n + 50)` with `n` the number of explicit ratings, and `model` is the
active trained model's prediction (see `Model`; all candidates are scored in one
batch). Without a model, `alpha` and `model` are 0 and ranking is rules-only. The
channel score is a Bayesian average of the channel's rating values shrunk toward its
curation prior with weight `k = 5`.

Similarity features compare a candidate's embedding with those of the videos rated top
tier (A-- and up) and bottom tier (D++ and down): the max and mean cosine similarity to
each set (`SimilarityFeatures`). They are passed to the model and, until the model can
weigh them itself, also make the rules-based `similarity` term: how much closer the
candidate's nearest top-tier video is than its nearest bottom-tier one, each counted
like a topic boost (only the part above `SIMILARITY_FLOOR`, since unrelated texts still
have some similarity). Candidates without an embedding get no similarity features and a
`similarity` term of 0.

Topic boosts: each topic adds `weight * max(0, cos_sim(video, topic) - 0.3) / 0.7` (see
`topic_boost`), with the topic's effective (decayed) weight. `breakdown.topics` maps a
topic's name to its boost, holding only the topics with a nonzero boost; videos without
an embedding (not enriched yet) get no topic boosts.

Unknown metadata passes the hard filters. Subscription candidates come from RSS, which
has no duration or live status, so most candidates have neither until they are enriched;
filtering them out would empty the feed. Shorts are still caught through `is_short`
(RSS marks them by their /shorts/ link) and, once known, a duration under 60 seconds.

Keyword mutes are matched against the title and description (see `KeywordMutes`).
"""

import math
import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from homefeed_core.curation import DEFAULT_PRIOR, PRIOR_VALUES, Prior, TopicVector
from homefeed_core.embeddings import Embedding, cosine_similarity, normalize

# Weight of the prior in the channel score, in "ratings' worth" (PLAN.md section 7).
CHANNEL_PRIOR_WEIGHT = 5
# Videos shorter than this are treated as Shorts.
SHORT_MAX_SECONDS = 60
# Number of explicit ratings at which a model's score gets half the weight.
ALPHA_HALF_RATINGS = 50
# Topic similarity below this gives no boost; the boost grows linearly from here to 1.
TOPIC_SIMILARITY_FLOOR = 0.3
# live_status values that are not (yet) a regular video.
LIVE_STATUSES = frozenset({"is_live", "is_upcoming"})
# Cosine similarity below which a rated video counts as unrelated (as for topic boosts).
SIMILARITY_FLOOR = 0.3
# Weight of the similarity term: a candidate as close to a top-tier video as possible,
# and unrelated to the bottom tier, gets this much (the channel score's range is [-1, 1]).
SIMILARITY_WEIGHT = 0.5


class FilterReason(StrEnum):
    SHORT = "short"
    LIVE = "live"
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    MUTED_CHANNEL = "muted_channel"
    MUTED_KEYWORD = "muted_keyword"
    WATCHED = "watched"
    DISMISSED = "dismissed"


@dataclass(frozen=True)
class RankCandidate:
    """A candidate video with the metadata the ranker needs. `None` means unknown."""

    video_id: str
    channel_id: str
    source: str
    source_detail: str | None = None
    title: str = ""
    description: str | None = None
    duration_seconds: int | None = None
    live_status: str | None = None
    is_short: bool = False
    published_at: str | None = None  # ISO 8601 UTC
    first_seen_at: str | None = None  # ISO 8601 UTC


@dataclass(frozen=True)
class ChannelCuration:
    prior: Prior = DEFAULT_PRIOR
    pinned: bool = False
    muted: bool = False


# Curation by channel id. Channels without an entry get the defaults (neutral prior).
Curation = Mapping[str, ChannelCuration]


@dataclass(frozen=True)
class DurationBounds:
    """Inclusive duration limits in seconds; `None` leaves that side open."""

    min_seconds: int | None = None
    max_seconds: int | None = None


NO_BOUNDS = DurationBounds()


class KeywordMutes:
    """Muted keywords, matched in a video's title and description ignoring case.

    A keyword matches as a whole word or phrase: "art" mutes "Pixel art" but not "Start
    here", and spaces in a phrase match any whitespace (titles wrap, descriptions break
    lines). Built once per ranking, since it compiles the keywords into one pattern.
    """

    def __init__(self, keywords: Iterable[str] = ()) -> None:
        alternatives = sorted(
            {r"\s+".join(map(re.escape, words)) for k in keywords if (words := k.split())}
        )
        self._pattern = (
            re.compile(rf"(?<!\w)(?:{'|'.join(alternatives)})(?!\w)", re.IGNORECASE)
            if alternatives
            else None
        )

    def matches(self, *texts: str | None) -> bool:
        if self._pattern is None:
            return False
        return any(text and self._pattern.search(text) for text in texts)


NO_KEYWORD_MUTES = KeywordMutes()


@dataclass(frozen=True)
class History:
    """What the user has already done with videos, for the watched/dismissed filters."""

    watched: Collection[str] = frozenset()
    dismissed: Collection[str] = frozenset()
    # Explicit rating values (-1 to 1) by channel id, for the channel score.
    channel_ratings: Mapping[str, Sequence[float]] = field(default_factory=dict)
    # Total number of explicit ratings, for alpha.
    n_ratings: int = 0


@dataclass(frozen=True)
class RatedTiers:
    """Embeddings of the rated top-tier (A-- and up) and bottom-tier (D++ and down)
    videos, by video id. Rated videos without an embedding are left out."""

    top: Mapping[str, Embedding] = field(default_factory=dict)
    bottom: Mapping[str, Embedding] = field(default_factory=dict)


NO_RATED_TIERS = RatedTiers()


@dataclass(frozen=True)
class TierSimilarity:
    """Cosine similarity of a candidate to the videos of one tier set."""

    max: float
    mean: float
    nearest_video_id: str  # the rated video `max` is the similarity to

    def to_dict(self) -> dict[str, object]:
        return {"max": self.max, "mean": self.mean, "nearest_video_id": self.nearest_video_id}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "TierSimilarity | None":
        if data is None:
            return None
        return cls(max=data["max"], mean=data["mean"], nearest_video_id=data["nearest_video_id"])


@dataclass(frozen=True)
class SimilarityFeatures:
    """A candidate's similarity to the top-tier and bottom-tier sets; a side is None
    when that set is empty."""

    top_tier: TierSimilarity | None = None
    bottom_tier: TierSimilarity | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "top_tier": self.top_tier.to_dict() if self.top_tier else None,
            "bottom_tier": self.bottom_tier.to_dict() if self.bottom_tier else None,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any] | None) -> "SimilarityFeatures | None":
        if data is None:
            return None
        return cls(
            top_tier=TierSimilarity.from_dict(data.get("top_tier")),
            bottom_tier=TierSimilarity.from_dict(data.get("bottom_tier")),
        )


@dataclass(frozen=True)
class ScoreBreakdown:
    """The terms of a score, which sum to `final`:
    `alpha * model + channel + similarity + sum(topics)`.

    `similarity_features` is not a term: it is what the `similarity` term (and the
    model) were computed from, kept for display. None without an embedding.
    """

    model: float = 0.0
    alpha: float = 0.0
    channel: float = 0.0
    similarity: float = 0.0
    topics: Mapping[str, float] = field(default_factory=dict)
    similarity_features: SimilarityFeatures | None = None

    @property
    def final(self) -> float:
        return self.alpha * self.model + self.channel + self.similarity + sum(self.topics.values())

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "alpha": self.alpha,
            "channel": self.channel,
            "similarity": self.similarity,
            "topics": dict(self.topics),
            "final": self.final,
            "similarity_features": (
                self.similarity_features.to_dict() if self.similarity_features else None
            ),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ScoreBreakdown":
        """Read back `to_dict` output (`final` is recomputed). Missing terms are 0, as
        in breakdowns stored before they existed."""
        return cls(
            model=data["model"],
            alpha=data["alpha"],
            channel=data["channel"],
            similarity=data.get("similarity", 0.0),
            topics=data.get("topics", {}),
            similarity_features=SimilarityFeatures.from_dict(data.get("similarity_features")),
        )


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: RankCandidate
    breakdown: ScoreBreakdown
    channel_prior: Prior
    channel_rating_count: int

    @property
    def score(self) -> float:
        return self.breakdown.final


@dataclass(frozen=True)
class ModelCandidate:
    """What the model is given about a candidate that passed the hard filters."""

    candidate: RankCandidate
    similarity: SimilarityFeatures | None  # None without an embedding
    embedding: Embedding | None
    channel_score: float


# Scores a batch of candidates at once, one score per candidate in the same order, in
# the same [-1, 1] space as rating values. homefeed_core.ranking_models.ranker_model
# wraps a trained `RankingModel` as one.
Model = Callable[[Sequence[ModelCandidate]], Sequence[float]]


def channel_score(prior: Prior, ratings: Sequence[float], k: int = CHANNEL_PRIOR_WEIGHT) -> float:
    """`(sum(ratings) + prior * k) / (n + k)`: the prior until ratings outweigh it."""
    return (sum(ratings) + PRIOR_VALUES[prior] * k) / (len(ratings) + k)


def alpha(n_ratings: int, *, has_model: bool) -> float:
    """The model's weight in the blend: `n / (n + 50)`, or 0 without a model."""
    if not has_model or n_ratings <= 0:
        return 0.0
    return n_ratings / (n_ratings + ALPHA_HALF_RATINGS)


def similarity_features(embedding: Sequence[float], tiers: RatedTiers) -> SimilarityFeatures:
    """Max and mean cosine similarity of `embedding` to the top-tier and bottom-tier
    sets."""
    return _similarity_features(embedding, _normalized(tiers.top), _normalized(tiers.bottom))


def similarity_score(features: SimilarityFeatures | None) -> float:
    """The rules-based `similarity` term, in [-SIMILARITY_WEIGHT, SIMILARITY_WEIGHT]:
    `weight * (affinity(top_tier.max) - affinity(bottom_tier.max))`, where
    `affinity(s) = max(0, s - SIMILARITY_FLOOR) / (1 - SIMILARITY_FLOOR)`."""
    if features is None:
        return 0.0

    def affinity(tier: TierSimilarity | None) -> float:
        if tier is None:
            return 0.0
        return max(0.0, tier.max - SIMILARITY_FLOOR) / (1 - SIMILARITY_FLOOR)

    return SIMILARITY_WEIGHT * (affinity(features.top_tier) - affinity(features.bottom_tier))


def _normalized(tier: Mapping[str, Sequence[float]]) -> dict[str, Embedding]:
    return {video_id: normalize(vector) for video_id, vector in tier.items()}


def _similarity_features(
    embedding: Sequence[float], top: Mapping[str, Embedding], bottom: Mapping[str, Embedding]
) -> SimilarityFeatures:
    """`similarity_features` with the tier sets already normalized."""
    unit = normalize(embedding)
    return SimilarityFeatures(_tier_similarity(unit, top), _tier_similarity(unit, bottom))


def _tier_similarity(unit: Embedding, tier: Mapping[str, Embedding]) -> TierSimilarity | None:
    """For unit vectors, cosine similarity is the dot product."""
    if not tier:
        return None
    similarities = {video_id: math.sumprod(unit, vector) for video_id, vector in tier.items()}
    nearest = max(similarities, key=similarities.__getitem__)
    return TierSimilarity(
        max=similarities[nearest],
        mean=sum(similarities.values()) / len(similarities),
        nearest_video_id=nearest,
    )


def topic_boost(weight: float, similarity: float) -> float:
    """`weight * max(0, similarity - 0.3) / 0.7`: 0 up to the floor, `weight` at 1."""
    return weight * max(0.0, similarity - TOPIC_SIMILARITY_FLOOR) / (1 - TOPIC_SIMILARITY_FLOOR)


def topic_boosts(embedding: Embedding | None, topics: Iterable[TopicVector]) -> dict[str, float]:
    """Each topic's boost for a video with `embedding`, by topic name; zeros left out."""
    if embedding is None:
        return {}
    boosts: dict[str, float] = {}
    for topic in topics:
        boost = topic_boost(topic.weight, cosine_similarity(embedding, topic.embedding))
        if boost != 0:
            boosts[topic.name] = boost
    return boosts


def filter_reason(
    candidate: RankCandidate,
    *,
    curation: Curation,
    history: History,
    bounds: DurationBounds = NO_BOUNDS,
    keyword_mutes: KeywordMutes = NO_KEYWORD_MUTES,
) -> FilterReason | None:
    """Why the candidate is dropped before scoring, or `None` if it passes."""
    duration = candidate.duration_seconds
    if candidate.is_short or (duration is not None and duration < SHORT_MAX_SECONDS):
        return FilterReason.SHORT
    if candidate.live_status in LIVE_STATUSES:
        return FilterReason.LIVE
    if duration is not None and bounds.min_seconds is not None and duration < bounds.min_seconds:
        return FilterReason.TOO_SHORT
    if duration is not None and bounds.max_seconds is not None and duration > bounds.max_seconds:
        return FilterReason.TOO_LONG
    if curation.get(candidate.channel_id, ChannelCuration()).muted:
        return FilterReason.MUTED_CHANNEL
    if keyword_mutes.matches(candidate.title, candidate.description):
        return FilterReason.MUTED_KEYWORD
    if candidate.video_id in history.watched:
        return FilterReason.WATCHED
    if candidate.video_id in history.dismissed:
        return FilterReason.DISMISSED
    return None


def rank(
    candidates: Iterable[RankCandidate],
    *,
    curation: Curation,
    history: History,
    bounds: DurationBounds = NO_BOUNDS,
    keyword_mutes: KeywordMutes = NO_KEYWORD_MUTES,
    embeddings: Mapping[str, Embedding] | None = None,
    rated_tiers: RatedTiers = NO_RATED_TIERS,
    model: Model | None = None,
    topics: Sequence[TopicVector] = (),
) -> list[ScoredCandidate]:
    """Filter and score `candidates`, best first (ties keep the input order).

    `embeddings` holds candidate embeddings by video id, for similarity features and
    topic boosts; candidates without one get neither."""
    embeddings = embeddings or {}
    blend = alpha(history.n_ratings, has_model=model is not None)
    top_tier, bottom_tier = _normalized(rated_tiers.top), _normalized(rated_tiers.bottom)
    channel_scores: dict[str, float] = {}
    passed: list[ModelCandidate] = []
    for candidate in candidates:
        if filter_reason(
            candidate,
            curation=curation,
            history=history,
            bounds=bounds,
            keyword_mutes=keyword_mutes,
        ):
            continue
        channel_id = candidate.channel_id
        if channel_id not in channel_scores:
            channel_scores[channel_id] = channel_score(
                curation.get(channel_id, ChannelCuration()).prior,
                history.channel_ratings.get(channel_id, ()),
            )
        embedding = embeddings.get(candidate.video_id)
        features = (
            None if embedding is None else _similarity_features(embedding, top_tier, bottom_tier)
        )
        passed.append(ModelCandidate(candidate, features, embedding, channel_scores[channel_id]))
    model_scores = _model_scores(model, passed)
    scored: list[ScoredCandidate] = []
    for item, model_score in zip(passed, model_scores, strict=True):
        candidate = item.candidate
        breakdown = ScoreBreakdown(
            model=model_score,
            alpha=blend,
            channel=item.channel_score,
            similarity=similarity_score(item.similarity),
            similarity_features=item.similarity,
            topics=topic_boosts(item.embedding, topics) if topics else {},
        )
        scored.append(
            ScoredCandidate(
                candidate,
                breakdown,
                curation.get(candidate.channel_id, ChannelCuration()).prior,
                len(history.channel_ratings.get(candidate.channel_id, ())),
            )
        )
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored


def _model_scores(model: Model | None, items: Sequence[ModelCandidate]) -> list[float]:
    """The model's score for each item (one batch call), or 0s without a model."""
    if model is None or not items:
        return [0.0] * len(items)
    scores = [float(score) for score in model(items)]
    if len(scores) != len(items):
        raise ValueError(f"The model returned {len(scores)} scores for {len(items)} candidates")
    return scores
