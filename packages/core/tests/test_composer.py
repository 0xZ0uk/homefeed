import random
from collections import Counter

from homefeed_core.composer import ComposeSettings, FeedSlot, compose, explain
from homefeed_core.curation import Prior
from homefeed_core.ranker import (
    ChannelCuration,
    RankCandidate,
    ScoreBreakdown,
    ScoredCandidate,
)


def channel(n: int) -> str:
    return f"UC{n:022d}"


def scored(
    video_id: str,
    channel_id: str,
    score: float,
    *,
    published_at: str | None = None,
    prior: Prior = "neutral",
    rating_count: int = 0,
) -> ScoredCandidate:
    return ScoredCandidate(
        candidate=RankCandidate(
            video_id=video_id,
            channel_id=channel_id,
            source="subscription",
            published_at=published_at,
        ),
        breakdown=ScoreBreakdown(channel=score),
        channel_prior=prior,
        channel_rating_count=rating_count,
    )


def pool(channels: int, per_channel: int) -> list[ScoredCandidate]:
    """`per_channel` videos for each of `channels` channels, channel i scoring i / 100."""
    return [
        scored(f"c{c}v{v}", channel(c), c / 100, published_at=f"2026-10-{10 + v:02d}T00:00:00Z")
        for c in range(channels)
        for v in range(per_channel)
    ]


def video_ids(slots: list[FeedSlot]) -> list[str]:
    return [slot.item.candidate.video_id for slot in slots]


def test_exact_feed_size() -> None:
    slots = compose(pool(20, 3), {}, ComposeSettings(size=15), random.Random(1))

    assert len(slots) == 15
    assert [slot.position for slot in slots] == list(range(15))


def test_short_pool_gives_every_eligible_item() -> None:
    slots = compose(pool(3, 1), {}, ComposeSettings(size=15), random.Random(1))

    assert len(slots) == 3


def test_top_scored_first() -> None:
    slots = compose(pool(20, 1), {}, ComposeSettings(size=5), random.Random(1))

    assert video_ids(slots) == ["c19v0", "c18v0", "c17v0", "c16v0", "c15v0"]


def test_per_channel_cap() -> None:
    items = pool(1, 5) + pool(10, 1)[1:]  # one channel with 5 videos scoring 0, others above

    slots = compose(items, {}, ComposeSettings(size=15), random.Random(1))
    best = compose(pool(2, 10), {}, ComposeSettings(size=15, per_channel_cap=2), random.Random(1))

    assert Counter(slot.item.candidate.channel_id for slot in slots)[channel(0)] == 2
    assert len(slots) == 11
    assert len(best) == 4
    assert max(Counter(slot.item.candidate.channel_id for slot in best).values()) == 2


def test_pins_always_included_and_first() -> None:
    items = pool(30, 2)
    pinned = channel(0)  # the lowest-scoring channel
    curation = {pinned: ChannelCuration(pinned=True)}

    slots = compose(items, curation, ComposeSettings(size=15), random.Random(1))

    assert [slot.is_pinned for slot in slots[:2]] == [True, True]
    assert {slot.item.candidate.channel_id for slot in slots[:2]} == {pinned}
    assert not any(slot.is_pinned for slot in slots[2:])
    assert len(slots) == 15
    assert slots[0].explanation.startswith("New from a pinned channel")


def test_pins_respect_cap_and_size() -> None:
    curation = {channel(c): ChannelCuration(pinned=True) for c in range(10)}

    slots = compose(pool(10, 3), curation, ComposeSettings(size=5), random.Random(1))

    assert len(slots) == 5
    assert all(slot.is_pinned for slot in slots)


def test_ties_prefer_newer_uploads() -> None:
    items = pool(1, 5)

    slots = compose(items, {}, ComposeSettings(size=15), random.Random(1))

    assert video_ids(slots) == ["c0v4", "c0v3"]


def test_deterministic_with_seeded_rng() -> None:
    # Equal scores and unknown publish times: only the rng breaks ties.
    items = [scored(f"v{i}", channel(i), 0.0) for i in range(40)]

    first = video_ids(compose(items, {}, ComposeSettings(size=15), random.Random(42)))
    again = video_ids(compose(items, {}, ComposeSettings(size=15), random.Random(42)))
    others = {
        tuple(video_ids(compose(items, {}, ComposeSettings(size=15), random.Random(seed))))
        for seed in range(5)
    }

    assert first == again
    assert len(others) > 1


def test_no_exploration_yet() -> None:
    slots = compose(pool(20, 1), {}, ComposeSettings(size=15), random.Random(1))

    assert not any(slot.is_exploration for slot in slots)
    assert all(slot.selection_probability is None for slot in slots)


def test_explanations() -> None:
    loved = scored("a", channel(1), 0.8, prior="love")
    rated = scored("b", channel(2), 0.25, prior="love", rating_count=3)
    neutral = scored("c", channel(3), 0.0)

    assert explain(loved) == "New from your subscriptions · channel you love"
    assert explain(rated) == "New from your subscriptions · channel score +0.25 from 3 ratings"
    assert explain(neutral) == "New from your subscriptions"
    assert explain(neutral, pinned=True) == "New from a pinned channel"
