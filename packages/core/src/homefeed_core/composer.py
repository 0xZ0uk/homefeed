"""Turning ranked candidates into a finite feed (PLAN.md section 7). Pure: no I/O; the
only randomness comes from the injected `rng`.

Order: pins first (candidates from pinned channels), then the top-scored rest, with at
most `per_channel_cap` items per channel overall (pins included) and exactly `size`
items when there are enough candidates. Exploration slots arrive in Milestone 3.

Equal scores are common in a rules-only feed (every video of a channel shares its
channel score), so ties go to the more recently published video, then to `rng`.
"""

import random
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from homefeed_core.candidates import SUBSCRIPTION
from homefeed_core.ranker import ChannelCuration, Curation, ScoredCandidate

DEFAULT_FEED_SIZE = 15
DEFAULT_PER_CHANNEL_CAP = 2

_PRIOR_PHRASES = {
    "love": "channel you love",
    "like": "channel you like",
    "skeptical": "channel you're skeptical of",
}


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
) -> list[FeedSlot]:
    """Pick and order up to `settings.size` items from `scored`."""
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
            explanation=explain(item, pinned=is_pinned),
            is_pinned=is_pinned,
        )
        for position, (item, is_pinned) in enumerate(chosen)
    ]


def explain(item: ScoredCandidate, *, pinned: bool = False) -> str:
    """One line on why the item is in the feed, from its source and channel score."""
    if pinned:
        source = "New from a pinned channel"
    elif item.candidate.source == SUBSCRIPTION:
        source = "New from your subscriptions"
    else:
        source = f"Found via {item.candidate.source}"
    count = item.channel_rating_count
    if count:
        plural = "rating" if count == 1 else "ratings"
        channel = f"channel score {item.breakdown.channel:+.2f} from {count} {plural}"
    else:
        channel = _PRIOR_PHRASES.get(item.channel_prior)
    return f"{source} · {channel}" if channel else source


def _order(scored: Sequence[ScoredCandidate], rng: random.Random) -> list[ScoredCandidate]:
    """Best score first; ties to the newest upload, then at random."""
    shuffled = list(scored)
    rng.shuffle(shuffled)
    shuffled.sort(key=lambda item: item.candidate.published_at or "", reverse=True)
    shuffled.sort(key=lambda item: item.score, reverse=True)
    return shuffled


def _curation(curation: Curation, item: ScoredCandidate) -> ChannelCuration:
    return curation.get(item.candidate.channel_id, ChannelCuration())
