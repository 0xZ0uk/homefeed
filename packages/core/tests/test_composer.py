import random
from collections import Counter

from homefeed_core.composer import (
    ComposeSettings,
    FeedSlot,
    VideoRef,
    compose,
    explain,
    referenced_video_ids,
)
from homefeed_core.curation import Prior
from homefeed_core.ranker import (
    ChannelCuration,
    RankCandidate,
    ScoreBreakdown,
    ScoredCandidate,
    SimilarityFeatures,
    TierSimilarity,
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
    source: str = "subscription",
    source_detail: str | None = None,
    breakdown: ScoreBreakdown | None = None,
) -> ScoredCandidate:
    return ScoredCandidate(
        candidate=RankCandidate(
            video_id=video_id,
            channel_id=channel_id,
            source=source,
            source_detail=source_detail,
            published_at=published_at,
        ),
        breakdown=breakdown or ScoreBreakdown(channel=score),
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


RATED = {
    "seed": VideoRef("How to sharpen a chisel", "A+"),
    "near": VideoRef("Dovetails by hand", "S-"),
    "unrated": VideoRef("Some video"),
}


def similar_to(video_id: str, similarity: float, *, channel: float = 0.0) -> ScoreBreakdown:
    """A breakdown whose nearest top-tier video is `video_id`."""
    features = SimilarityFeatures(top_tier=TierSimilarity(0.9, 0.5, video_id))
    return ScoreBreakdown(channel=channel, similarity=similarity, similarity_features=features)


def test_explanations_name_the_largest_positive_term() -> None:
    similar = scored(
        "a", channel(1), 0, prior="love", breakdown=similar_to("near", 0.4, channel=0.3)
    )
    loved = scored("b", channel(1), 0, prior="love", breakdown=similar_to("near", 0.2, channel=0.8))
    disliked = scored("c", channel(1), 0, breakdown=similar_to("near", -0.3))

    assert explain(similar, videos=RATED) == (
        "New from your subscriptions · similar to Dovetails by hand (S-)"
    )
    assert explain(loved, videos=RATED) == "New from your subscriptions · channel you love"
    assert explain(disliked, videos=RATED) == "New from your subscriptions"


def test_explanations_for_topic_terms() -> None:
    topics = {"woodworking": 0.6, "metalwork": 0.2, "drama": -0.9}
    item = scored(
        "a", channel(1), 0, prior="like", breakdown=ScoreBreakdown(channel=0.4, topics=topics)
    )

    assert explain(item) == "New from your subscriptions · matches your topic 'woodworking'"


def test_explanations_for_the_model_term() -> None:
    item = scored("a", channel(1), 0, breakdown=ScoreBreakdown(model=0.3, alpha=0.5, channel=0.1))

    assert explain(item) == "New from your subscriptions · the model predicts B++"


def test_explanations_for_related_videos() -> None:
    def related(seed: str, breakdown: ScoreBreakdown) -> ScoredCandidate:
        return scored(
            "r",
            channel(1),
            0,
            prior="love",
            source="related",
            source_detail=seed,
            breakdown=breakdown,
        )

    loved = related("seed", ScoreBreakdown(channel=0.8))
    similar = related("seed", similar_to("near", 0.4))
    # Similar to its own seed: the next largest term explains it instead.
    own_seed = related("seed", similar_to("seed", 0.4, channel=0.3))
    only_own_seed = related("seed", similar_to("seed", 0.4))

    assert explain(loved, videos=RATED) == (
        "Related to How to sharpen a chisel (A+) · channel you love"
    )
    assert explain(similar, videos=RATED) == (
        "Related to How to sharpen a chisel (A+) · similar to Dovetails by hand (S-)"
    )
    assert explain(own_seed, videos=RATED) == (
        "Related to How to sharpen a chisel (A+) · channel you love"
    )
    assert explain(only_own_seed, videos=RATED) == "Related to How to sharpen a chisel (A+)"


def test_explanations_without_titles_or_grades() -> None:
    long_title = {"seed": VideoRef("x" * 100, "A")}
    unknown = scored("a", channel(1), 0, source="related", source_detail="gone")
    unrated = scored("b", channel(1), 0, source="related", source_detail="unrated")
    long = scored("c", channel(1), 0, source="related", source_detail="seed")
    other = scored("d", channel(1), 0, source="saved_search")

    assert explain(unknown, videos=RATED) == "Related to a video you rated highly"
    assert explain(unrated, videos=RATED) == "Related to Some video"
    assert explain(long, videos=long_title) == f"Related to {'x' * 59}… (A)"
    assert explain(other) == "Found via saved search"


def test_compose_explains_with_the_given_videos() -> None:
    items = [
        scored("a", channel(1), 0, source="related", source_detail="seed"),
        scored("b", channel(2), 0, breakdown=similar_to("near", 0.5)),
        scored("c", channel(3), 0),
    ]

    slots = compose(items, {}, ComposeSettings(size=15), random.Random(1), videos=RATED)

    assert referenced_video_ids(items) == {"seed", "near"}
    assert {slot.item.candidate.video_id: slot.explanation for slot in slots} == {
        "a": "Related to How to sharpen a chisel (A+)",
        "b": "New from your subscriptions · similar to Dovetails by hand (S-)",
        "c": "New from your subscriptions",
    }
