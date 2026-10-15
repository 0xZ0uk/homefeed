import random
from collections import Counter

from homefeed_core.composer import (
    EXPLORATION_MAX_RATINGS,
    ChannelRatings,
    ComposeSettings,
    FeedSlot,
    VideoRef,
    compose,
    explain,
    followed_topics,
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


# Settings without exploration, for tests of the rest of the composition.
NO_EXPLORATION = ComposeSettings(exploration_slots=0)


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
    slots = compose(pool(20, 1), {}, ComposeSettings(size=5, exploration_slots=0), random.Random(1))

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


def tagged(
    video_id: str, channel_id: str, score: float, *topics: str, boost: float = 0.5
) -> ScoredCandidate:
    """An item with the final `score` that matched the `topics`, each boosted by `boost`."""
    breakdown = ScoreBreakdown(
        channel=score - boost * len(topics), tags=dict.fromkeys(topics, boost)
    )
    return scored(video_id, channel_id, score, breakdown=breakdown)


def topic_count(slots: list[FeedSlot], topic: str) -> int:
    return sum(topic in followed_topics(slot.item) for slot in slots)


def share(size: int, max_topic_share: float) -> ComposeSettings:
    return ComposeSettings(size=size, exploration_slots=0, max_topic_share=max_topic_share)


def test_a_followed_topic_takes_at_most_its_share_of_the_feed() -> None:
    godot = [tagged(f"g{n}", channel(n), 0.9 - n / 100, "Godot") for n in range(12)]
    others = [scored(f"o{n}", channel(20 + n), 0.1 - n / 100) for n in range(8)]

    slots = compose([*godot, *others], {}, share(10, 0.4), random.Random(1))

    # ceil(0.4 * 10) = 4 picks: the best four, then the others although they score lower.
    assert video_ids(slots) == ["g0", "g1", "g2", "g3", *(f"o{n}" for n in range(6))]
    assert topic_count(slots, "Godot") == 4


def test_deferred_items_fill_the_feed_when_nothing_else_can() -> None:
    godot = [tagged(f"g{n}", channel(n), 0.9 - n / 100, "Godot") for n in range(12)]
    others = [scored(f"o{n}", channel(20 + n), 0.1 - n / 100) for n in range(3)]

    slots = compose([*godot, *others], {}, share(10, 0.4), random.Random(1))

    # Never short of the size: the deferred picks come last, best first.
    assert video_ids(slots) == ["g0", "g1", "g2", "g3", "o0", "o1", "o2", "g4", "g5", "g6"]
    assert [slot.position for slot in slots] == list(range(10))


def test_an_item_is_deferred_when_any_of_its_topics_is_full() -> None:
    items = [
        tagged("a", channel(1), 0.9, "Godot"),
        tagged("b", channel(2), 0.8, "Godot", "Game development"),
        tagged("c", channel(3), 0.7, "Game development"),
        tagged("d", channel(4), 0.6, "Godot", "Game development"),
        scored("e", channel(5), 0.1),
        scored("f", channel(6), 0.05),
    ]

    slots = compose(items, {}, share(4, 0.5), random.Random(1))

    # Two picks per topic: "d" has two topics, and Godot is full.
    assert video_ids(slots) == ["a", "b", "c", "e"]
    assert topic_count(slots, "Godot") == topic_count(slots, "Game development") == 2


def test_pins_are_never_capped_but_count_towards_their_topics() -> None:
    pinned = [tagged(f"p{n}", channel(n), 0.0, "Godot") for n in range(4)]
    curation = {channel(n): ChannelCuration(pinned=True) for n in range(4)}
    godot = [tagged(f"g{n}", channel(10 + n), 0.9 - n / 100, "Godot") for n in range(3)]
    others = [scored(f"o{n}", channel(20 + n), 0.1 - n / 100) for n in range(6)]

    slots = compose([*pinned, *godot, *others], curation, share(8, 0.25), random.Random(1))

    # The cap is 2, and all four pins are in; the topic is full, so only others follow.
    assert [slot.is_pinned for slot in slots] == [True] * 4 + [False] * 4
    assert video_ids(slots[4:]) == ["o0", "o1", "o2", "o3"]


def test_a_muted_tag_is_no_topic() -> None:
    muted = [tagged(f"d{n}", channel(n), 0.5 - n / 100, "Drama", boost=-0.5) for n in range(6)]
    other = scored("o", channel(20), 0.1)

    slots = compose([*muted, other], {}, share(5, 0.2), random.Random(1))

    assert followed_topics(muted[0]) == ()
    assert video_ids(slots) == ["d0", "d1", "d2", "d3", "d4"]


def test_a_share_of_one_leaves_the_feed_as_ranked() -> None:
    godot = [tagged(f"g{n}", channel(n), 0.9 - n / 100, "Godot") for n in range(12)]
    others = [scored(f"o{n}", channel(20 + n), 0.1 - n / 100) for n in range(8)]

    slots = compose([*godot, *others], {}, share(10, 1.0), random.Random(1))

    assert video_ids(slots) == [f"g{n}" for n in range(10)]


def test_an_exploration_pick_whose_topic_is_full_waits_with_the_rest() -> None:
    items = [tagged(f"g{n}", channel(n), 0.9 - n / 100, "Godot") for n in range(3)]
    settings = ComposeSettings(size=10, exploration_slots=3, max_topic_share=0.2)

    slots = compose(items, {}, settings, random.Random(1))

    # Three channels share three slots, but only two picks may be Godot: the third is
    # still in the feed, as a plain pick.
    assert [(slot.item.candidate.video_id, slot.is_exploration) for slot in slots] == [
        ("g0", True),
        ("g1", True),
        ("g2", False),
    ]


def test_the_topic_share_rounds_up_to_whole_picks() -> None:
    assert ComposeSettings().max_topic_share == 0.4
    assert ComposeSettings(size=20, max_topic_share=0.4).max_per_topic == 8
    assert ComposeSettings(size=15, max_topic_share=0.4).max_per_topic == 6
    assert ComposeSettings(size=7, max_topic_share=0.25).max_per_topic == 2  # 1.75
    assert ComposeSettings(size=50, max_topic_share=0.14).max_per_topic == 7  # not float noise's 8
    assert ComposeSettings(size=3, max_topic_share=0.1).max_per_topic == 1
    assert ComposeSettings(size=20, max_topic_share=0.0).max_per_topic == 1


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


def exploration(slots: list[FeedSlot]) -> list[FeedSlot]:
    return [slot for slot in slots if slot.is_exploration]


def rated(good: int, not_good: int = 0) -> ChannelRatings:
    return ChannelRatings(good=good, not_good=not_good)


def test_exploration_slot_count() -> None:
    slots = compose(pool(20, 1), {}, ComposeSettings(size=15), random.Random(1))
    none = compose(pool(20, 1), {}, NO_EXPLORATION, random.Random(1))
    five = compose(pool(20, 1), {}, ComposeSettings(size=15, exploration_slots=5), random.Random(1))

    assert len(slots) == 15
    assert [slot.is_exploration for slot in slots[:3]] == [True, True, True]
    assert not any(slot.is_exploration for slot in slots[3:])
    assert exploration(none) == []
    assert len(exploration(five)) == 5


def test_exploration_comes_after_pins() -> None:
    curation = {channel(0): ChannelCuration(pinned=True)}

    slots = compose(pool(20, 2), curation, ComposeSettings(size=15), random.Random(1))

    assert [(slot.is_pinned, slot.is_exploration) for slot in slots[:6]] == [
        (True, False),
        (True, False),
        (False, True),
        (False, True),
        (False, True),
        (False, False),
    ]
    # Pinned channels are pins, never exploration.
    assert all(slot.item.candidate.channel_id != channel(0) for slot in exploration(slots))


def test_exploration_fits_in_the_feed_size() -> None:
    curation = {channel(c): ChannelCuration(pinned=True) for c in range(2)}

    full = compose(pool(10, 3), curation, ComposeSettings(size=4), random.Random(1))
    room_for_one = compose(pool(10, 3), curation, ComposeSettings(size=5), random.Random(1))

    assert exploration(full) == []
    assert len(exploration(room_for_one)) == 1
    assert len(room_for_one) == 5


def test_exploration_only_for_under_rated_channels() -> None:
    items = pool(10, 1)
    # Every channel but 3 and 7 has enough ratings to be left out of exploration.
    ratings = {channel(c): rated(EXPLORATION_MAX_RATINGS) for c in range(10) if c not in (3, 7)}
    ratings[channel(3)] = rated(2, EXPLORATION_MAX_RATINGS - 3)  # one short of the limit

    slots = compose(items, {}, ComposeSettings(), random.Random(1), channel_ratings=ratings)

    explored = exploration(slots)
    assert {slot.item.candidate.channel_id for slot in explored} == {channel(3), channel(7)}
    # Only two eligible channels for three slots: both are certain to be picked.
    assert [slot.selection_probability for slot in explored] == [1.0, 1.0]


def test_exploration_picks_one_video_per_channel_and_respects_the_cap() -> None:
    items = pool(2, 4)  # two channels, both eligible, four videos each

    slots = compose(items, {}, ComposeSettings(size=15), random.Random(1))

    explored = exploration(slots)
    assert len(explored) == 2
    assert len({slot.item.candidate.channel_id for slot in explored}) == 2
    # The channel's best-ranked (newest) video takes the slot; the cap still applies.
    assert {slot.item.candidate.video_id for slot in explored} == {"c0v3", "c1v3"}
    assert len(slots) == 4
    assert len(set(video_ids(slots))) == 4


def test_exploration_probabilities_recorded() -> None:
    items = pool(10, 1)

    slots = compose(items, {}, ComposeSettings(), random.Random(1))

    explored = exploration(slots)
    assert len(explored) == 3
    for slot in explored:
        assert slot.selection_probability is not None
        # Ten channels with the same posterior share three slots: about 0.3 each.
        assert 0.2 < slot.selection_probability < 0.4
    assert all(slot.selection_probability is None for slot in slots if not slot.is_exploration)


def test_exploration_favours_promising_channels() -> None:
    items = pool(10, 1)
    ratings = {channel(c): rated(0, 4) for c in range(10)}
    ratings[channel(0)] = rated(4)  # 4 good ratings: Beta(5, 1) against Beta(1, 5)

    slots = compose(
        items,
        {},
        ComposeSettings(exploration_slots=1),
        random.Random(1),
        channel_ratings=ratings,
    )

    [explored] = exploration(slots)
    assert explored.item.candidate.channel_id == channel(0)
    assert explored.selection_probability is not None
    assert explored.selection_probability > 0.9


def test_exploration_deterministic_with_seeded_rng() -> None:
    items = pool(30, 2)

    def run(seed: int) -> list[tuple[str, float | None]]:
        slots = compose(items, {}, ComposeSettings(), random.Random(seed))
        return [(s.item.candidate.video_id, s.selection_probability) for s in exploration(slots)]

    assert run(7) == run(7)
    assert len({tuple(run(seed)) for seed in range(5)}) > 1


def test_exploration_explanations() -> None:
    items = [
        scored("a", channel(1), 0.5, source="related", source_detail="seed"),
        scored("b", channel(2), 0.4),
    ]
    ratings = {channel(2): rated(1, 1)}

    slots = compose(
        items, {}, ComposeSettings(), random.Random(1), videos=RATED, channel_ratings=ratings
    )

    assert {slot.item.candidate.video_id: slot.explanation for slot in slots} == {
        "a": "Exploring: new channel · related to “How to sharpen a chisel”, which you rated 8",
        "b": "Exploring: channel with 2 ratings · new from your subscriptions",
    }


def test_explanations() -> None:
    loved = scored("a", channel(1), 0.8, prior="love")
    rated = scored("b", channel(2), 0.25, prior="love", rating_count=3)
    neutral = scored("c", channel(3), 0.0)

    assert explain(loved) == "New from your subscriptions · channel you love"
    assert explain(rated) == "New from your subscriptions · channel score +0.25 from 3 ratings"
    assert explain(neutral) == "New from your subscriptions"
    assert explain(neutral, pinned=True) == "New from a pinned channel"


RATED = {
    "seed": VideoRef("How to sharpen a chisel", 8),
    "near": VideoRef("Dovetails by hand", 9),
    "unrated": VideoRef("Some video"),
    "more": VideoRef("Mortise and tenon", feedback=1),
    "less": VideoRef("A dull saw", feedback=-1),
    "both": VideoRef("Rated and marked", 3, feedback=1),  # the rating wins
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
        "New from your subscriptions · similar to “Dovetails by hand”, which you rated 9"
    )
    assert explain(loved, videos=RATED) == "New from your subscriptions · channel you love"
    assert explain(disliked, videos=RATED) == "New from your subscriptions"


def test_explanations_for_tag_terms() -> None:
    tags = {"woodworking": 0.6, "metalwork": 0.2, "drama": -0.9}
    item = scored(
        "a", channel(1), 0, prior="like", breakdown=ScoreBreakdown(channel=0.4, tags=tags)
    )

    assert explain(item) == "New from your subscriptions · tagged 'woodworking', which you follow"


def test_explanations_for_the_model_term() -> None:
    item = scored("a", channel(1), 0, breakdown=ScoreBreakdown(model=0.3, alpha=0.5, channel=0.1))

    assert explain(item) == "New from your subscriptions · the model predicts 6.8"


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
        "Related to “How to sharpen a chisel”, which you rated 8 · channel you love"
    )
    assert explain(similar, videos=RATED) == (
        "Related to “How to sharpen a chisel”, which you rated 8 · "
        "similar to “Dovetails by hand”, which you rated 9"
    )
    assert explain(own_seed, videos=RATED) == (
        "Related to “How to sharpen a chisel”, which you rated 8 · channel you love"
    )
    assert explain(only_own_seed, videos=RATED) == (
        "Related to “How to sharpen a chisel”, which you rated 8"
    )


def test_explanations_without_titles_or_scores() -> None:
    long_title = {"seed": VideoRef("x" * 100, 8)}
    unknown = scored("a", channel(1), 0, source="related", source_detail="gone")
    unrated = scored("b", channel(1), 0, source="related", source_detail="unrated")
    long = scored("c", channel(1), 0, source="related", source_detail="seed")
    other = scored("d", channel(1), 0, source="saved_search")

    assert explain(unknown, videos=RATED) == "Related to a video you rated highly"
    assert explain(unrated, videos=RATED) == "Related to “Some video”"
    assert explain(long, videos=long_title) == f"Related to “{'x' * 59}…”, which you rated 8"
    assert explain(other) == "Found via saved search"
    featured = scored("e", channel(1), 0, source="channel_graph", source_detail="UC" + "a" * 22)
    assert explain(featured) == "Featured by a channel you like"


def test_explanations_name_videos_the_user_wanted_more_of() -> None:
    def similar(nearest: str) -> ScoredCandidate:
        return scored("a", channel(1), 0, breakdown=similar_to(nearest, 0.4))

    related = scored("r", channel(1), 0, source="related", source_detail="more")

    assert explain(similar("more"), videos=RATED) == (
        "New from your subscriptions · similar to “Mortise and tenon”, which you wanted more of"
    )
    assert (
        explain(related, videos=RATED) == "Related to “Mortise and tenon”, which you wanted more of"
    )
    # An explicit rating wins over feedback.
    assert explain(similar("both"), videos=RATED) == (
        "New from your subscriptions · similar to “Rated and marked”, which you rated 3"
    )
    # Nothing is claimed about a video the user wanted less of; only its title is named.
    assert explain(similar("less"), videos=RATED) == (
        "New from your subscriptions · similar to “A dull saw”"
    )


def test_explanations_for_videos_without_a_title() -> None:
    videos = {
        "rated": VideoRef("  ", 7),
        "more": VideoRef("", feedback=1),
        "plain": VideoRef(""),
    }

    def related(seed: str) -> str:
        item = scored("r", channel(1), 0, source="related", source_detail=seed)
        return explain(item, videos=videos)

    assert related("rated") == "Related to a video you rated 7"
    assert related("more") == "Related to a video you wanted more of"
    assert related("plain") == "Related to a video you rated highly"


def test_explains_saved_search_candidates_by_their_query() -> None:
    found = scored("a", channel(1), 0.8, prior="love", source="saved_search", source_detail="wood")
    long = scored("b", channel(1), 0, source="saved_search", source_detail="q" * 100)

    assert explain(found) == "From your 'wood' search · channel you love"
    assert explain(found, exploration=ChannelRatings(0, 0)) == (
        "Exploring: new channel · from your 'wood' search"
    )
    assert explain(long) == f"From your '{'q' * 59}…' search"


def test_compose_explains_with_the_given_videos() -> None:
    items = [
        scored("a", channel(1), 0, source="related", source_detail="seed"),
        scored("b", channel(2), 0, breakdown=similar_to("near", 0.5)),
        scored("c", channel(3), 0),
    ]

    slots = compose(items, {}, NO_EXPLORATION, random.Random(1), videos=RATED)

    assert referenced_video_ids(items) == {"seed", "near"}
    assert {slot.item.candidate.video_id: slot.explanation for slot in slots} == {
        "a": "Related to “How to sharpen a chisel”, which you rated 8",
        "b": "New from your subscriptions · similar to “Dovetails by hand”, which you rated 9",
        "c": "New from your subscriptions",
    }


def test_explains_tag_candidates_by_their_tag() -> None:
    found = scored("a", channel(1), 0, source="tag", source_detail="woodworking")

    assert explain(found) == "Because you follow #woodworking"
