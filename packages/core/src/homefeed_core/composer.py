"""Turning ranked candidates into a finite feed (PLAN.md section 7). Pure: no I/O; the
only randomness comes from the injected `rng`.

Order: pins first (candidates from pinned channels), then the top-scored rest, with at
most `per_channel_cap` items per channel overall (pins included) and exactly `size`
items when there are enough candidates. Exploration slots arrive in Milestone 3.

Equal scores are common in a rules-only feed (every video of a channel shares its
channel score), so ties go to the more recently published video, then to `rng`.

Every slot gets a one-line explanation (`explain`): where the item came from, then the
largest positive term of its score breakdown, e.g. "Related to X (A+) · channel you
love". Explanations name rated videos (the seed of a related video, the nearest
top-tier video of a similar one), so `compose` takes their titles and grades as
`videos`; `referenced_video_ids` says which ones to look up.
"""

import random
from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType

from homefeed_core.candidates import RELATED, SUBSCRIPTION
from homefeed_core.grades import Grade, nearest_grade
from homefeed_core.ranker import ChannelCuration, Curation, ScoredCandidate

DEFAULT_FEED_SIZE = 15
DEFAULT_PER_CHANNEL_CAP = 2

_PRIOR_PHRASES = {
    "love": "channel you love",
    "like": "channel you like",
}
# Video titles in explanations are cut to this many characters.
TITLE_MAX_LENGTH = 60


@dataclass(frozen=True)
class VideoRef:
    """A video an explanation names: its title and, if rated, its grade."""

    title: str
    grade: Grade | None = None


# Video refs by video id.
VideoRefs = Mapping[str, VideoRef]
NO_VIDEO_REFS: VideoRefs = MappingProxyType({})


@dataclass(frozen=True)
class ComposeSettings:
    size: int = DEFAULT_FEED_SIZE
    per_channel_cap: int = DEFAULT_PER_CHANNEL_CAP


@dataclass(frozen=True)
class FeedSlot:
    item: ScoredCandidate
    position: int  # 0-based
    explanation: str
    is_pinned: bool = False
    is_exploration: bool = False
    selection_probability: float | None = None  # exploration items only (Milestone 3)


def compose(
    scored: Sequence[ScoredCandidate],
    curation: Curation,
    settings: ComposeSettings,
    rng: random.Random,
    *,
    videos: VideoRefs = NO_VIDEO_REFS,
) -> list[FeedSlot]:
    """Pick and order up to `settings.size` items from `scored`. `videos` holds the
    videos explanations may name (see `referenced_video_ids`)."""
    ordered = _order(scored, rng)
    pinned = [item for item in ordered if _curation(curation, item).pinned]
    rest = [item for item in ordered if not _curation(curation, item).pinned]

    per_channel: Counter[str] = Counter()
    chosen: list[tuple[ScoredCandidate, bool]] = []
    for group, is_pinned in ((pinned, True), (rest, False)):
        for item in group:
            if len(chosen) >= settings.size:
                break
            channel_id = item.candidate.channel_id
            if per_channel[channel_id] >= settings.per_channel_cap:
                continue
            per_channel[channel_id] += 1
            chosen.append((item, is_pinned))

    return [
        FeedSlot(
            item=item,
            position=position,
            explanation=explain(item, pinned=is_pinned, videos=videos),
            is_pinned=is_pinned,
        )
        for position, (item, is_pinned) in enumerate(chosen)
    ]


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
    item: ScoredCandidate, *, pinned: bool = False, videos: VideoRefs = NO_VIDEO_REFS
) -> str:
    """One line on why the item is in the feed: its source, then the largest positive
    term of its score breakdown (if any), e.g. "Related to X (A+) · channel you love".

    A term that would only repeat the source (similarity to the very video a related
    video came from) gives way to the next largest one."""
    source, source_video_id = _source_phrase(item, pinned=pinned, videos=videos)
    reason = _reason_phrase(item, videos=videos, skip_video_id=source_video_id)
    return f"{source} · {reason}" if reason else source


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
            (value, lambda name=name: f"matches your topic '{name}'")
            for name, value in sorted(breakdown.topics.items())
        ),
        (
            breakdown.alpha * breakdown.model,
            lambda: f"the model predicts {nearest_grade(breakdown.model)}",
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
    """ "Title (A+)", or a stand-in for an unknown title or grade."""
    if ref is None:
        return "a video you rated highly"
    title = ref.title.strip()
    if len(title) > TITLE_MAX_LENGTH:
        title = title[: TITLE_MAX_LENGTH - 1].rstrip() + "…"
    if not title:
        return f"a video you rated {ref.grade}" if ref.grade else "a video you rated highly"
    return f"{title} ({ref.grade})" if ref.grade else title


def _order(scored: Sequence[ScoredCandidate], rng: random.Random) -> list[ScoredCandidate]:
    """Best score first; ties to the newest upload, then at random."""
    shuffled = list(scored)
    rng.shuffle(shuffled)
    shuffled.sort(key=lambda item: item.candidate.published_at or "", reverse=True)
    shuffled.sort(key=lambda item: item.score, reverse=True)
    return shuffled


def _curation(curation: Curation, item: ScoredCandidate) -> ChannelCuration:
    return curation.get(item.candidate.channel_id, ChannelCuration())
