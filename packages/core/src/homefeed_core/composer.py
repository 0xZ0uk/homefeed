"""Turning ranked candidates into a finite feed (PLAN.md section 7). Pure: no I/O; the
only randomness comes from the injected `rng`.

Order: pins first (candidates from pinned channels), then exploration slots, then the
top-scored rest, with at most `per_channel_cap` items per channel overall (pins and
exploration included) and exactly `size` items when there are enough candidates.

Exploration slots (`exploration_slots`, default 3) go to under-rated channels: those
with fewer than `EXPLORATION_MAX_RATINGS` ratings, including never-rated channels from
new sources. Each is picked by Thompson sampling: draw once from every eligible
channel's `Beta(good + 1, not_good + 1)` posterior (good = 6 or higher; see
`ChannelRatings`) and take the channels with the highest draws, one slot each, filled
by the channel's best-ranked video. The chance an item gets its slot is estimated by
Monte Carlo over `exploration_draws` such draws (the first of them is the one used) and
stored as its `selection_probability`, so training can reweight exploration ratings by
its inverse.

Equal scores are common in a rules-only feed (every video of a channel shares its
channel score), so ties go to the more recently published video, then to `rng`.

Every slot gets a one-line explanation (`explain`): where the item came from, then the
largest positive term of its score breakdown, e.g. "Related to X (8) · channel you
love". Explanations name rated videos (the seed of a related video, the nearest
top-tier video of a similar one), so `compose` takes their titles and scores as
`videos`; `referenced_video_ids` says which ones to look up.
"""

import random
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from types import MappingProxyType

from homefeed_core.candidates import CHANNEL_GRAPH, RELATED, SAVED_SEARCH, SUBSCRIPTION, TAG
from homefeed_core.external_sources import EXTERNAL
from homefeed_core.ranker import ChannelCuration, Curation, ScoredCandidate
from homefeed_core.scores import value_score

DEFAULT_FEED_SIZE = 20
DEFAULT_PER_CHANNEL_CAP = 2
DEFAULT_EXPLORATION_SLOTS = 3
# Monte Carlo draws to estimate exploration selection probabilities.
DEFAULT_EXPLORATION_DRAWS = 500
# Channels with fewer ratings than this are eligible for exploration slots.
EXPLORATION_MAX_RATINGS = 5

_PRIOR_PHRASES = {
    "love": "channel you love",
    "like": "channel you like",
}
# Video titles in explanations are cut to this many characters.
TITLE_MAX_LENGTH = 60


@dataclass(frozen=True)
class VideoRef:
    """A video an explanation names: its title and, if rated, its score."""

    title: str
    score: int | None = None


# Video refs by video id.
VideoRefs = Mapping[str, VideoRef]
NO_VIDEO_REFS: VideoRefs = MappingProxyType({})


@dataclass(frozen=True)
class ChannelRatings:
    """How a channel's videos were rated: good (6 or higher) and not good."""

    good: int = 0
    not_good: int = 0

    @property
    def total(self) -> int:
        return self.good + self.not_good


# Rating counts by channel id; channels missing are never rated.
ChannelRatingCounts = Mapping[str, ChannelRatings]
NO_CHANNEL_RATINGS: ChannelRatingCounts = MappingProxyType({})


@dataclass(frozen=True)
class ComposeSettings:
    size: int = DEFAULT_FEED_SIZE
    per_channel_cap: int = DEFAULT_PER_CHANNEL_CAP
    exploration_slots: int = DEFAULT_EXPLORATION_SLOTS
    exploration_draws: int = DEFAULT_EXPLORATION_DRAWS


@dataclass(frozen=True)
class FeedSlot:
    item: ScoredCandidate
    position: int  # 0-based
    explanation: str
    is_pinned: bool = False
    is_exploration: bool = False
    # The estimated chance an exploration item got its slot; None for other items.
    selection_probability: float | None = None


def compose(
    scored: Sequence[ScoredCandidate],
    curation: Curation,
    settings: ComposeSettings,
    rng: random.Random,
    *,
    videos: VideoRefs = NO_VIDEO_REFS,
    channel_ratings: ChannelRatingCounts = NO_CHANNEL_RATINGS,
) -> list[FeedSlot]:
    """Pick and order up to `settings.size` items from `scored`. `videos` holds the
    videos explanations may name (see `referenced_video_ids`); `channel_ratings` the
    rating counts that decide exploration (channels missing are never rated)."""
    ordered = _order(scored, rng)
    pinned = [item for item in ordered if _curation(curation, item).pinned]
    rest = [item for item in ordered if not _curation(curation, item).pinned]

    per_channel: Counter[str] = Counter()
    chosen: list[FeedSlot] = []

    def take(
        item: ScoredCandidate,
        *,
        is_pinned: bool = False,
        is_exploration: bool = False,
        selection_probability: float | None = None,
    ) -> bool:
        channel_id = item.candidate.channel_id
        if len(chosen) >= settings.size or per_channel[channel_id] >= settings.per_channel_cap:
            return False
        per_channel[channel_id] += 1
        chosen.append(
            FeedSlot(
                item=item,
                position=len(chosen),
                explanation="",  # filled in below
                is_pinned=is_pinned,
                is_exploration=is_exploration,
                selection_probability=selection_probability,
            )
        )
        return True

    for item in pinned:
        take(item, is_pinned=True)

    slots = min(settings.exploration_slots, settings.size - len(chosen))
    explored: set[str] = set()
    for item, probability in _explore(rest, channel_ratings, slots, settings, rng):
        if take(item, is_exploration=True, selection_probability=probability):
            explored.add(item.candidate.video_id)

    for item in rest:
        if item.candidate.video_id not in explored:
            take(item)

    return [
        replace(
            slot,
            explanation=explain(
                slot.item,
                pinned=slot.is_pinned,
                exploration=(
                    channel_ratings.get(slot.item.candidate.channel_id, ChannelRatings())
                    if slot.is_exploration
                    else None
                ),
                videos=videos,
            ),
        )
        for slot in chosen
    ]


def _explore(
    ordered: Sequence[ScoredCandidate],
    channel_ratings: ChannelRatingCounts,
    slots: int,
    settings: ComposeSettings,
    rng: random.Random,
) -> list[tuple[ScoredCandidate, float]]:
    """Up to `slots` exploration items from `ordered` (best first), one per channel,
    each with its estimated selection probability. See the module docstring."""
    # The best-ranked video of each eligible channel, in `ordered` order.
    best: dict[str, ScoredCandidate] = {}
    for item in ordered:
        channel_id = item.candidate.channel_id
        counts = channel_ratings.get(channel_id, ChannelRatings())
        if channel_id not in best and counts.total < EXPLORATION_MAX_RATINGS:
            best[channel_id] = item
    if slots <= 0 or not best:
        return []

    channels = list(best)
    if len(channels) <= slots:  # every eligible channel gets a slot
        return [(item, 1.0) for item in best.values()]
    posteriors = [
        (counts.good + 1, counts.not_good + 1)
        for counts in (channel_ratings.get(c, ChannelRatings()) for c in channels)
    ]
    draws = max(1, settings.exploration_draws)
    wins: Counter[str] = Counter()
    picked: list[str] = []
    for draw in range(draws):
        samples = [rng.betavariate(a, b) for a, b in posteriors]
        top = sorted(range(len(channels)), key=lambda i: samples[i], reverse=True)[:slots]
        winners = [channels[i] for i in top]
        wins.update(winners)
        if draw == 0:
            picked = winners
    return [(best[channel_id], wins[channel_id] / draws) for channel_id in picked]


def referenced_video_ids(scored: Iterable[ScoredCandidate]) -> set[str]:
    """The videos the explanations of `scored` may name: seeds of related videos and
    the nearest top-tier video of each similar one."""
    ids: set[str] = set()
    for item in scored:
        if item.candidate.source == RELATED and item.candidate.source_detail:
            ids.add(item.candidate.source_detail)
        features = item.breakdown.similarity_features
        if features and features.top_tier:
            ids.add(features.top_tier.nearest_video_id)
    return ids


def explain(
    item: ScoredCandidate,
    *,
    pinned: bool = False,
    exploration: ChannelRatings | None = None,
    videos: VideoRefs = NO_VIDEO_REFS,
) -> str:
    """One line on why the item is in the feed: its source, then the largest positive
    term of its score breakdown (if any), e.g. "Related to X (8) · channel you love".
    An exploration item (`exploration` holds its channel's rating counts) says so
    first, e.g. "Exploring: new channel · related to X (8)".

    A term that would only repeat the source (similarity to the very video a related
    video came from) gives way to the next largest one."""
    source, source_video_id = _source_phrase(item, pinned=pinned, videos=videos)
    if exploration is not None:
        return f"{_exploration_phrase(exploration)} · {source[:1].lower()}{source[1:]}"
    reason = _reason_phrase(item, videos=videos, skip_video_id=source_video_id)
    return f"{source} · {reason}" if reason else source


def _exploration_phrase(counts: ChannelRatings) -> str:
    if not counts.total:
        return "Exploring: new channel"
    plural = "rating" if counts.total == 1 else "ratings"
    return f"Exploring: channel with {counts.total} {plural}"


def _source_phrase(
    item: ScoredCandidate, *, pinned: bool, videos: VideoRefs
) -> tuple[str, str | None]:
    """Where the item came from, and the video it names (if any)."""
    candidate = item.candidate
    if pinned:
        return "New from a pinned channel", None
    if candidate.source == SUBSCRIPTION:
        return "New from your subscriptions", None
    if candidate.source == RELATED:
        seed = candidate.source_detail
        return f"Related to {_describe_video(videos.get(seed) if seed else None)}", seed
    if candidate.source == SAVED_SEARCH and candidate.source_detail:
        query = candidate.source_detail.strip()
        if len(query) > TITLE_MAX_LENGTH:
            query = query[: TITLE_MAX_LENGTH - 1].rstrip() + "…"
        return f"From your '{query}' search", None
    if candidate.source == CHANNEL_GRAPH:
        return "Featured by a channel you like", None
    if candidate.source == TAG and candidate.source_detail:
        return f"Because you follow #{candidate.source_detail}", None
    if candidate.source == EXTERNAL and candidate.source_detail:
        return f"Linked from {candidate.source_detail}", None
    return f"Found via {candidate.source.replace('_', ' ')}", None


def _reason_phrase(
    item: ScoredCandidate, *, videos: VideoRefs, skip_video_id: str | None
) -> str | None:
    """A phrase for the largest positive breakdown term, or None if none is positive."""
    breakdown = item.breakdown
    # (value, phrase) per term; a phrase is None when the term is better left unsaid.
    terms: list[tuple[float, Callable[[], str | None]]] = [
        (breakdown.channel, lambda: _channel_phrase(item)),
        (breakdown.similarity, lambda: _similarity_phrase(item, videos, skip_video_id)),
        *(
            (value, lambda label=label: f"tagged '{label}', which you follow")
            for label, value in sorted(breakdown.tags.items())
        ),
        (
            breakdown.alpha * breakdown.model,
            lambda: f"the model predicts {value_score(breakdown.model):.1f}",
        ),
    ]
    # Largest first; equal terms keep the order above (the sort is stable).
    for value, phrase in sorted(terms, key=lambda term: term[0], reverse=True):
        if value <= 0:
            return None
        if (text := phrase()) is not None:
            return text
    return None


def _channel_phrase(item: ScoredCandidate) -> str | None:
    count = item.channel_rating_count
    if count:
        plural = "rating" if count == 1 else "ratings"
        return f"channel score {item.breakdown.channel:+.2f} from {count} {plural}"
    return _PRIOR_PHRASES.get(item.channel_prior)


def _similarity_phrase(
    item: ScoredCandidate, videos: VideoRefs, skip_video_id: str | None
) -> str | None:
    features = item.breakdown.similarity_features
    nearest = features.top_tier.nearest_video_id if features and features.top_tier else None
    if nearest is not None and nearest == skip_video_id:
        return None
    return f"similar to {_describe_video(videos.get(nearest) if nearest else None)}"


def _describe_video(ref: VideoRef | None) -> str:
    """ "Title (8)", or a stand-in for an unknown title or score."""
    if ref is None:
        return "a video you rated highly"
    rated = ref.score is not None
    title = ref.title.strip()
    if len(title) > TITLE_MAX_LENGTH:
        title = title[: TITLE_MAX_LENGTH - 1].rstrip() + "…"
    if not title:
        return f"a video you rated {ref.score}" if rated else "a video you rated highly"
    return f"{title} ({ref.score})" if rated else title


def _order(scored: Sequence[ScoredCandidate], rng: random.Random) -> list[ScoredCandidate]:
    """Best score first; ties to the newest upload, then at random."""
    shuffled = list(scored)
    rng.shuffle(shuffled)
    shuffled.sort(key=lambda item: item.candidate.published_at or "", reverse=True)
    shuffled.sort(key=lambda item: item.score, reverse=True)
    return shuffled


def _curation(curation: Curation, item: ScoredCandidate) -> ChannelCuration:
    return curation.get(item.candidate.channel_id, ChannelCuration())
