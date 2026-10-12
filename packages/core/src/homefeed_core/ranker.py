"""Scoring feed candidates (PLAN.md section 7). Pure: no I/O, everything is passed in.

`rank` drops candidates that fail a hard filter, scores the rest and returns them best
first. Each score comes with a breakdown whose parts sum to it:

    final = alpha * model + channel + sum(topics)

Milestone 1 is rules-only: there is no model (so `alpha` and `model` are 0) and no
topics, which leaves the channel score, a Bayesian average of the channel's rating
values shrunk toward its curation prior with weight `k = 5`.

Unknown metadata passes the hard filters. Subscription candidates come from RSS, which
has no duration or live status, so most candidates have neither until they are enriched;
filtering them out would empty the feed. Shorts are still caught through `is_short`
(RSS marks them by their /shorts/ link) and, once known, a duration under 60 seconds.
"""

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from homefeed_core.curation import DEFAULT_PRIOR, PRIOR_VALUES, Prior

# Weight of the prior in the channel score, in "ratings' worth" (PLAN.md section 7).
CHANNEL_PRIOR_WEIGHT = 5
# Videos shorter than this are treated as Shorts.
SHORT_MAX_SECONDS = 60
# Number of explicit ratings at which a model's score gets half the weight.
ALPHA_HALF_RATINGS = 50
# live_status values that are not (yet) a regular video.
LIVE_STATUSES = frozenset({"is_live", "is_upcoming"})


class FilterReason(StrEnum):
    SHORT = "short"
    LIVE = "live"
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    MUTED_CHANNEL = "muted_channel"
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
class ScoreBreakdown:
    model: float = 0.0
    alpha: float = 0.0
    channel: float = 0.0
    topics: Mapping[str, float] = field(default_factory=dict)

    @property
    def final(self) -> float:
        return self.alpha * self.model + self.channel + sum(self.topics.values())

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "alpha": self.alpha,
            "channel": self.channel,
            "topics": dict(self.topics),
            "final": self.final,
        }


@dataclass(frozen=True)
class ScoredCandidate:
    candidate: RankCandidate
    breakdown: ScoreBreakdown
    channel_prior: Prior
    channel_rating_count: int

    @property
    def score(self) -> float:
        return self.breakdown.final


# Scores a candidate in the same [-1, 1] space as rating values (Milestone 3).
Model = Callable[[RankCandidate], float]


def channel_score(prior: Prior, ratings: Sequence[float], k: int = CHANNEL_PRIOR_WEIGHT) -> float:
    """`(sum(ratings) + prior * k) / (n + k)`: the prior until ratings outweigh it."""
    return (sum(ratings) + PRIOR_VALUES[prior] * k) / (len(ratings) + k)


def alpha(n_ratings: int, *, has_model: bool) -> float:
    """The model's weight in the blend: `n / (n + 50)`, or 0 without a model."""
    if not has_model or n_ratings <= 0:
        return 0.0
    return n_ratings / (n_ratings + ALPHA_HALF_RATINGS)


def filter_reason(
    candidate: RankCandidate,
    *,
    curation: Curation,
    history: History,
    bounds: DurationBounds = NO_BOUNDS,
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
    model: Model | None = None,
) -> list[ScoredCandidate]:
    """Filter and score `candidates`, best first (ties keep the input order)."""
    blend = alpha(history.n_ratings, has_model=model is not None)
    channel_scores: dict[str, float] = {}
    scored: list[ScoredCandidate] = []
    for candidate in candidates:
        if filter_reason(candidate, curation=curation, history=history, bounds=bounds):
            continue
        channel_id = candidate.channel_id
        prior = curation.get(channel_id, ChannelCuration()).prior
        ratings = history.channel_ratings.get(channel_id, ())
        if channel_id not in channel_scores:
            channel_scores[channel_id] = channel_score(prior, ratings)
        breakdown = ScoreBreakdown(
            model=model(candidate) if model is not None else 0.0,
            alpha=blend,
            channel=channel_scores[channel_id],
        )
        scored.append(ScoredCandidate(candidate, breakdown, prior, len(ratings)))
    scored.sort(key=lambda item: item.score, reverse=True)
    return scored
