import json
import math
from collections.abc import Sequence
from typing import Any

import pytest

from homefeed_core.curation import TagSubscription
from homefeed_core.embeddings import EMBEDDING_DIMENSIONS, normalize
from homefeed_core.llm_tags import LLMTags
from homefeed_core.ranker import (
    CHANNEL_PRIOR_WEIGHT,
    SIMILARITY_FLOOR,
    SIMILARITY_WEIGHT,
    ChannelCuration,
    DurationBounds,
    FilterReason,
    History,
    KeywordMutes,
    ModelCandidate,
    RankCandidate,
    RatedTiers,
    ScoreBreakdown,
    SimilarityFeatures,
    TierSimilarity,
    alpha,
    channel_score,
    filter_reason,
    rank,
    similarity_features,
    similarity_score,
    tag_boosts,
)
from homefeed_core.scores import score_value

CHANNEL = "UC" + "a" * 22
OTHER = "UC" + "b" * 22


def candidate(video_id: str = "v1", channel_id: str = CHANNEL, **kwargs: Any) -> RankCandidate:
    return RankCandidate(video_id=video_id, channel_id=channel_id, source="subscription", **kwargs)


def ids(candidates: list[RankCandidate], **kwargs: Any) -> list[str]:
    return [item.candidate.video_id for item in rank(candidates, **kwargs)]


NO_HISTORY = History()


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"is_short": True}, FilterReason.SHORT),
        ({"duration_seconds": 59}, FilterReason.SHORT),
        ({"live_status": "is_live"}, FilterReason.LIVE),
        ({"live_status": "is_upcoming"}, FilterReason.LIVE),
        ({"duration_seconds": 60}, None),
        ({"live_status": "was_live"}, None),
        ({"live_status": "not_live", "duration_seconds": 600}, None),
    ],
)
def test_filters_shorts_and_live(kwargs: dict[str, Any], reason: FilterReason | None) -> None:
    assert filter_reason(candidate(**kwargs), curation={}, history=NO_HISTORY) == reason


def test_filters_out_of_range_durations() -> None:
    bounds = DurationBounds(min_seconds=120, max_seconds=3600)
    videos = [
        candidate("short", duration_seconds=119),
        candidate("low", duration_seconds=120),
        candidate("high", duration_seconds=3600),
        candidate("long", duration_seconds=3601),
    ]

    assert [filter_reason(v, curation={}, history=NO_HISTORY, bounds=bounds) for v in videos] == [
        FilterReason.TOO_SHORT,
        None,
        None,
        FilterReason.TOO_LONG,
    ]
    assert ids(videos, curation={}, history=NO_HISTORY, bounds=bounds) == ["low", "high"]


def test_unknown_duration_and_live_status_pass() -> None:
    bounds = DurationBounds(min_seconds=120, max_seconds=3600)
    unknown = candidate(duration_seconds=None, live_status=None)

    assert filter_reason(unknown, curation={}, history=NO_HISTORY, bounds=bounds) is None


def test_filters_muted_channels() -> None:
    curation = {CHANNEL: ChannelCuration(prior="love", muted=True)}
    videos = [candidate("muted", CHANNEL), candidate("kept", OTHER)]

    assert ids(videos, curation=curation, history=NO_HISTORY) == ["kept"]


def test_filters_muted_keywords_in_title_and_description() -> None:
    mutes = KeywordMutes(["crypto", "Reaction  Video"])
    videos = [
        candidate("title", title="Why CRYPTO crashed"),
        candidate("description", title="Weekly news", description="Today: crypto, AI"),
        candidate("phrase", title="My reaction\nvideo to the trailer"),
        candidate("plain", title="Woodworking basics", description=None),
        candidate("inside_word", title="Cryptography explained"),
    ]

    assert [
        filter_reason(v, curation={}, history=NO_HISTORY, keyword_mutes=mutes) for v in videos
    ] == [
        FilterReason.MUTED_KEYWORD,
        FilterReason.MUTED_KEYWORD,
        FilterReason.MUTED_KEYWORD,
        None,
        None,
    ]
    assert ids(videos, curation={}, history=NO_HISTORY, keyword_mutes=mutes) == [
        "plain",
        "inside_word",
    ]


@pytest.mark.parametrize(
    ("keyword", "title", "muted"),
    [
        ("art", "Pixel art for beginners", True),
        ("art", "Start here", False),
        ("c++", "Learning C++ in a week", True),
        ("#shorts", "Funny cat #shorts", True),
        ("café", "CAFÉ tour", True),
        ("a.b", "axb", False),
    ],
)
def test_keyword_matching(keyword: str, title: str, muted: bool) -> None:
    assert KeywordMutes([keyword]).matches(title) is muted


def test_no_keyword_mutes_match_nothing() -> None:
    assert KeywordMutes().matches("anything", None) is False
    assert KeywordMutes(["", "  "]).matches("anything") is False


def test_filters_watched_and_dismissed() -> None:
    history = History(watched={"watched"}, dismissed={"dismissed"})
    videos = [candidate("watched"), candidate("dismissed"), candidate("fresh")]

    assert filter_reason(videos[0], curation={}, history=history) == FilterReason.WATCHED
    assert filter_reason(videos[1], curation={}, history=history) == FilterReason.DISMISSED
    assert ids(videos, curation={}, history=history) == ["fresh"]


def test_channel_score_is_the_prior_without_ratings() -> None:
    assert channel_score("love", []) == pytest.approx(0.8)
    assert channel_score("like", []) == pytest.approx(0.4)
    assert channel_score("neutral", []) == 0.0
    assert channel_score("skeptical", []) == pytest.approx(-0.4)


def test_channel_score_moves_from_prior_toward_evidence() -> None:
    bad = score_value(3)
    scores = [channel_score("love", [bad] * n) for n in (0, 1, 5, 20, 200)]

    assert scores[0] == pytest.approx(0.8)
    assert all(a > b for a, b in zip(scores, scores[1:], strict=False))
    assert scores[2] == pytest.approx((0.8 + bad) / 2)  # k = 5: five ratings weigh as the prior
    assert scores[-1] == pytest.approx(bad, abs=0.05)
    assert CHANNEL_PRIOR_WEIGHT == 5


def test_unknown_channel_gets_neutral_prior() -> None:
    [scored] = rank([candidate(channel_id=OTHER)], curation={}, history=NO_HISTORY)

    assert scored.channel_prior == "neutral"
    assert scored.score == 0.0


def test_rank_orders_by_channel_score() -> None:
    curation = {CHANNEL: ChannelCuration(prior="skeptical"), OTHER: ChannelCuration(prior="like")}
    history = History(channel_ratings={CHANNEL: [1.0] * 10}, n_ratings=10)
    videos = [candidate("liked", OTHER), candidate("proven", CHANNEL)]

    scored = rank(videos, curation=curation, history=history)

    assert [item.candidate.video_id for item in scored] == ["proven", "liked"]
    assert scored[0].breakdown.channel == pytest.approx((10 - 0.4 * 5) / 15)
    assert scored[0].channel_rating_count == 10
    assert scored[1].breakdown.channel == pytest.approx(0.4)


def test_alpha_is_zero_without_model_or_ratings() -> None:
    assert alpha(0, has_model=False) == 0.0
    assert alpha(0, has_model=True) == 0.0
    assert alpha(120, has_model=False) == 0.0
    assert alpha(50, has_model=True) == pytest.approx(0.5)

    history = History(channel_ratings={CHANNEL: [0.5] * 3}, n_ratings=3)
    [scored] = rank([candidate()], curation={}, history=history)
    assert scored.breakdown.alpha == 0.0
    assert scored.breakdown.model == 0.0


def test_breakdown_sums_to_final_score() -> None:
    curation = {CHANNEL: ChannelCuration(prior="love")}
    history = History(channel_ratings={CHANNEL: [0.2, -0.6, 1.0]}, n_ratings=30)
    videos = [candidate("a"), candidate("b", OTHER)]

    for model in (None, lambda items: [0.7] * len(items)):
        for item in rank(videos, curation=curation, history=history, model=model):
            b = item.breakdown
            parts = b.alpha * b.model + b.channel + b.similarity + sum(b.tags.values())
            assert math.isclose(item.score, parts)
            assert b.to_dict()["final"] == item.score


def test_breakdown_with_model_and_tags() -> None:
    breakdown = ScoreBreakdown(
        model=0.5, alpha=0.4, channel=0.1, similarity=0.05, tags={"woodworking": 0.2}
    )

    assert breakdown.final == pytest.approx(0.2 + 0.1 + 0.05 + 0.2)
    assert breakdown.to_dict() == {
        "model": 0.5,
        "alpha": 0.4,
        "channel": 0.1,
        "similarity": 0.05,
        "tags": {"woodworking": 0.2},
        "final": breakdown.final,
        "similarity_features": None,
    }
    assert ScoreBreakdown.from_dict(breakdown.to_dict()) == breakdown


def test_breakdown_reads_dicts_stored_before_similarity() -> None:
    old = {"model": 0.0, "alpha": 0.0, "channel": 0.4, "topics": {}, "final": 0.4}

    assert ScoreBreakdown.from_dict(old) == ScoreBreakdown(channel=0.4)


def test_breakdown_reads_topic_terms_stored_before_tags() -> None:
    old = {"model": 0.0, "alpha": 0.0, "channel": 0.4, "topics": {"wood": 0.2}, "final": 0.6}

    assert ScoreBreakdown.from_dict(old) == ScoreBreakdown(channel=0.4, tags={"wood": 0.2})


# Similarity features, with synthetic embeddings: unit axes and mixes of them.


def axis(i: int, dimensions: int = 4) -> tuple[float, ...]:
    return tuple(1.0 if j == i else 0.0 for j in range(dimensions))


def mix(*weights: float) -> tuple[float, ...]:
    return tuple(weights)


TIERS = RatedTiers(
    top={"loved1": axis(0), "loved2": axis(1)},
    bottom={"hated": axis(3)},
)


def test_similarity_features_max_and_mean_per_tier() -> None:
    features = similarity_features(mix(3, 4, 0, 0), TIERS)  # cos 0.6 to axis 0, 0.8 to 1

    assert features.top_tier is not None and features.bottom_tier is not None
    assert features.top_tier.max == pytest.approx(0.8)
    assert features.top_tier.mean == pytest.approx(0.7)
    assert features.top_tier.nearest_video_id == "loved2"
    assert features.bottom_tier.max == pytest.approx(0.0)
    assert features.bottom_tier.mean == pytest.approx(0.0)
    assert features.bottom_tier.nearest_video_id == "hated"


def test_similarity_is_cosine_regardless_of_vector_length() -> None:
    features = similarity_features(mix(10, 0, 0, 0), RatedTiers(top={"a": mix(0.5, 0.5, 0, 0)}))

    assert features.top_tier is not None
    assert features.top_tier.max == pytest.approx(math.sqrt(0.5))
    assert features.bottom_tier is None


def test_similarity_features_without_rated_tiers() -> None:
    assert similarity_features(axis(0), RatedTiers()) == SimilarityFeatures(None, None)
    assert similarity_score(SimilarityFeatures(None, None)) == 0.0
    assert similarity_score(None) == 0.0


def test_similarity_score_counts_closeness_above_the_floor() -> None:
    def features(top: float | None, bottom: float | None) -> SimilarityFeatures:
        return SimilarityFeatures(
            None if top is None else TierSimilarity(top, top, "t"),
            None if bottom is None else TierSimilarity(bottom, bottom, "b"),
        )

    assert similarity_score(features(1.0, None)) == pytest.approx(SIMILARITY_WEIGHT)
    assert similarity_score(features(None, 1.0)) == pytest.approx(-SIMILARITY_WEIGHT)
    assert similarity_score(features(SIMILARITY_FLOOR, 0.0)) == 0.0
    assert similarity_score(features(0.65, 0.2)) == pytest.approx(SIMILARITY_WEIGHT * 0.5)
    assert similarity_score(features(0.65, 0.65)) == pytest.approx(0.0)
    assert similarity_score(features(-0.5, -0.9)) == 0.0
    # Another embedding model's floor (see embeddings.calibration).
    assert similarity_score(features(0.2, None), floor=0.2) == 0.0
    assert similarity_score(features(0.6, None), floor=0.2) == pytest.approx(
        SIMILARITY_WEIGHT * 0.5
    )


def test_rank_uses_similarity_to_rated_tiers() -> None:
    videos = [
        candidate("like_hated", channel_id=OTHER),
        candidate("unrelated"),
        candidate("unenriched"),
        candidate("like_loved", channel_id=OTHER),
    ]
    embeddings = {
        "like_loved": mix(1, 0.1, 0, 0),
        "unrelated": axis(2),
        "like_hated": mix(0, 0, 0.1, 1),
    }

    scored = rank(videos, curation={}, history=NO_HISTORY, embeddings=embeddings, rated_tiers=TIERS)

    assert [item.candidate.video_id for item in scored] == [
        "like_loved",
        "unrelated",
        "unenriched",
        "like_hated",
    ]
    by_id = {item.candidate.video_id: item.breakdown for item in scored}
    assert by_id["like_loved"].similarity > 0.4
    assert by_id["like_hated"].similarity < -0.4
    assert by_id["unrelated"].similarity == 0.0
    assert by_id["unenriched"].similarity == 0.0
    assert by_id["unenriched"].similarity_features is None
    loved = by_id["like_loved"].similarity_features
    assert loved is not None and loved.top_tier is not None
    assert loved.top_tier.nearest_video_id == "loved1"
    assert loved == similarity_features(embeddings["like_loved"], TIERS)
    for item in scored:
        b = item.breakdown
        assert item.score == pytest.approx(b.channel + b.similarity)


def test_similarity_shows_in_breakdown_dict() -> None:
    [scored] = rank(
        [candidate()],
        curation={},
        history=NO_HISTORY,
        embeddings={"v1": mix(3, 4, 0, 0)},
        rated_tiers=TIERS,
    )
    data = scored.breakdown.to_dict()

    assert data["similarity"] == scored.breakdown.similarity
    assert data["similarity_features"] == {
        "top_tier": {
            "max": pytest.approx(0.8),
            "mean": pytest.approx(0.7),
            "nearest_video_id": "loved2",
        },
        "bottom_tier": {"max": 0.0, "mean": 0.0, "nearest_video_id": "hated"},
    }
    assert ScoreBreakdown.from_dict(json.loads(json.dumps(data))) == scored.breakdown


def test_model_gets_similarity_features() -> None:
    seen: dict[str, SimilarityFeatures | None] = {}

    def model(items: Sequence[ModelCandidate]) -> list[float]:
        seen.update({item.candidate.video_id: item.similarity for item in items})
        return [0.0] * len(items)

    rank(
        [candidate("a"), candidate("b")],
        curation={},
        history=NO_HISTORY,
        embeddings={"a": axis(0)},
        rated_tiers=TIERS,
        model=model,
    )

    assert seen == {"a": similarity_features(axis(0), TIERS), "b": None}


def test_model_gets_llm_tags() -> None:
    tags = LLMTags("science", depth=0.9, clickbait=0.1, rage_bait=0.0)
    seen: dict[str, LLMTags | None] = {}

    def model(items: Sequence[ModelCandidate]) -> list[float]:
        seen.update({item.candidate.video_id: item.tags for item in items})
        return [0.0] * len(items)

    scored = rank(
        [candidate("a"), candidate("b")],
        curation={},
        history=NO_HISTORY,
        llm_tags={"a": tags},
        model=model,
    )

    assert seen == {"a": tags, "b": None}
    # Tags reach the score only through the model.
    assert [item.score for item in scored] == [0.0, 0.0]


def test_model_scores_unfiltered_candidates_in_one_batch() -> None:
    calls: list[list[ModelCandidate]] = []

    def model(items: Sequence[ModelCandidate]) -> list[float]:
        calls.append(list(items))
        return [0.9 if item.candidate.video_id == "b" else -0.5 for item in items]

    curation = {CHANNEL: ChannelCuration(prior="like")}
    scored = rank(
        [candidate("a"), candidate("short", is_short=True), candidate("b", OTHER)],
        curation=curation,
        history=History(n_ratings=150),
        embeddings={"a": axis(0)},
        model=model,
    )

    [batch] = calls
    assert [item.candidate.video_id for item in batch] == ["a", "b"]
    assert batch[0].embedding == axis(0) and batch[1].embedding is None
    assert batch[0].channel_score == pytest.approx(0.4) and batch[1].channel_score == 0.0
    # alpha = 150 / 200; b's model score outweighs a's channel prior.
    assert [item.candidate.video_id for item in scored] == ["b", "a"]
    b, a = (item.breakdown for item in scored)
    assert b.alpha == a.alpha == pytest.approx(0.75)
    assert (b.model, a.model) == (0.9, -0.5)
    assert b.final == pytest.approx(0.9 * 0.75)
    assert a.final == pytest.approx(0.4 - 0.5 * 0.75)


def test_model_weight_grows_with_ratings() -> None:
    def model(items: Sequence[ModelCandidate]) -> list[float]:
        return [1.0] * len(items)

    for n, weight in [(0, 0.0), (50, 0.5), (150, 0.75)]:
        [scored] = rank([candidate()], curation={}, history=History(n_ratings=n), model=model)
        assert scored.breakdown.alpha == pytest.approx(weight)
        assert scored.breakdown.model == 1.0
        assert scored.score == pytest.approx(weight)


def test_model_must_score_every_candidate() -> None:
    with pytest.raises(ValueError, match="1 scores for 2 candidates"):
        rank(
            [candidate("a"), candidate("b")],
            curation={},
            history=NO_HISTORY,
            model=lambda items: [0.0],
        )


def test_model_is_not_called_without_candidates() -> None:
    def model(items: Sequence[ModelCandidate]) -> list[float]:
        raise AssertionError("called")

    assert rank([], curation={}, history=NO_HISTORY, model=model) == []


def with_similarity(similarity: float) -> tuple[float, ...]:
    """A unit vector whose cosine similarity to `unit(0)` is `similarity`, orthogonal to
    every other `unit(i)` but the last."""
    return normalize(
        [similarity] + [0.0] * (EMBEDDING_DIMENSIONS - 2) + [math.sqrt(1 - similarity**2)]
    )


def unit(index: int) -> tuple[float, ...]:
    return tuple(1.0 if i == index else 0.0 for i in range(EMBEDDING_DIMENSIONS))


def subscription(
    label: str, weight: float, *, tag_id: int = 7, hide: bool = False
) -> TagSubscription:
    return TagSubscription(
        tag_id=tag_id,
        slug=label.lower(),
        label=label,
        weight=weight,
        hide=hide,
        created_at="2026-10-12T06:00:00.000Z",
        updated_at="2026-10-12T06:00:00.000Z",
    )


def test_tag_boosts_are_weight_times_confidence() -> None:
    tags = [subscription("rust", 0.5)]

    assert tag_boosts(tags, {7: 0.8}) == {"rust": pytest.approx(0.4)}
    assert tag_boosts(tags, {7: 1.0}) == {"rust": pytest.approx(0.5)}
    assert tag_boosts(tags, {8: 1.0}) == {}  # another tag
    assert tag_boosts(tags, None) == {}
    assert tag_boosts([subscription("rust", -0.5)], {7: 0.6}) == {"rust": pytest.approx(-0.3)}
    assert tag_boosts([subscription("rust", 0.0)], {7: 1.0}) == {}  # zero weight: left out


def test_tag_boosts_sharing_a_label_add_up() -> None:
    tags = [subscription("Rust", 0.5, tag_id=7), subscription("Rust", 0.2, tag_id=8)]

    assert tag_boosts(tags, {7: 1.0, 8: 1.0}) == {"Rust": pytest.approx(0.7)}
    cancelling = [subscription("Rust", 0.5, tag_id=7), subscription("Rust", -0.5, tag_id=8)]
    assert tag_boosts(cancelling, {7: 1.0, 8: 1.0}) == {}


def test_rank_adds_tag_boosts_and_parts_sum_to_final() -> None:
    tags = [subscription("rust", 0.5), subscription("drama", -0.6, tag_id=8)]
    videos = [candidate("tagged"), candidate("plain"), candidate("both")]
    embeddings = {"plain": unit(2), "both": unit(1)}
    video_tags = {"tagged": {7: 1.0}, "both": {7: 0.5, 8: 1.0}}

    scored = rank(
        videos,
        curation={},
        history=NO_HISTORY,
        tags=tags,
        embeddings=embeddings,
        video_tags=video_tags,
    )

    by_id = {item.candidate.video_id: item for item in scored}
    assert by_id["tagged"].breakdown.tags == {"rust": pytest.approx(0.5)}
    assert by_id["both"].breakdown.tags == {
        "rust": pytest.approx(0.25),
        "drama": pytest.approx(-0.6),
    }
    assert by_id["plain"].breakdown.tags == {}
    assert [item.candidate.video_id for item in scored] == ["tagged", "plain", "both"]
    for item in scored:
        b = item.breakdown
        assert math.isclose(item.score, b.channel + sum(b.tags.values()))
        assert math.isclose(b.final, item.score)


def hiding_tag(*, hide: bool = True, tag_id: int = 7) -> TagSubscription:
    return subscription("rust", -1.0, tag_id=tag_id, hide=hide)


def test_hide_drops_videos_carrying_the_tag() -> None:
    videos = [candidate("hidden"), candidate("other-tag"), candidate("untagged")]
    video_tags = {"hidden": {7: 0.3}, "other-tag": {8: 1.0}}

    scored = rank(
        videos, curation={}, history=NO_HISTORY, tags=[hiding_tag()], video_tags=video_tags
    )

    assert {item.candidate.video_id for item in scored} == {"other-tag", "untagged"}


def test_a_muted_tag_without_hide_only_pushes_videos_down() -> None:
    videos = [candidate("tagged"), candidate("plain")]
    video_tags = {"tagged": {7: 1.0}}

    scored = rank(
        videos,
        curation={},
        history=NO_HISTORY,
        tags=[hiding_tag(hide=False)],
        video_tags=video_tags,
    )

    assert [item.candidate.video_id for item in scored] == ["plain", "tagged"]
    assert scored[1].breakdown.tags == {"rust": pytest.approx(-1.0)}
    assert scored[0].breakdown.tags == {}


def test_filter_reason_names_a_hidden_tag() -> None:
    reason = filter_reason(
        candidate(), curation={}, history=NO_HISTORY, hidden_tags={7}, tag_ids=[3, 7]
    )

    assert reason == FilterReason.HIDDEN_TAG
    assert filter_reason(candidate(), curation={}, history=NO_HISTORY, hidden_tags={7}) is None
