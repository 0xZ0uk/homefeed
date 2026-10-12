import json
import math
from typing import Any

import pytest

from homefeed_core.curation import TopicVector
from homefeed_core.embeddings import EMBEDDING_DIMENSIONS, normalize
from homefeed_core.grades import grade_value
from homefeed_core.ranker import (
    CHANNEL_PRIOR_WEIGHT,
    SIMILARITY_FLOOR,
    SIMILARITY_WEIGHT,
    ChannelCuration,
    DurationBounds,
    FilterReason,
    History,
    KeywordMutes,
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
    topic_boost,
    topic_boosts,
)

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
    bad = grade_value("D")
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

    for model in (None, lambda _c, _f: 0.7):
        for item in rank(videos, curation=curation, history=history, model=model):
            b = item.breakdown
            parts = b.alpha * b.model + b.channel + b.similarity + sum(b.topics.values())
            assert math.isclose(item.score, parts)
            assert b.to_dict()["final"] == item.score


def test_breakdown_with_model_and_topics() -> None:
    breakdown = ScoreBreakdown(
        model=0.5, alpha=0.4, channel=0.1, similarity=0.05, topics={"woodworking": 0.2}
    )

    assert breakdown.final == pytest.approx(0.2 + 0.1 + 0.05 + 0.2)
    assert breakdown.to_dict() == {
        "model": 0.5,
        "alpha": 0.4,
        "channel": 0.1,
        "similarity": 0.05,
        "topics": {"woodworking": 0.2},
        "final": breakdown.final,
        "similarity_features": None,
    }
    assert ScoreBreakdown.from_dict(breakdown.to_dict()) == breakdown


def test_breakdown_reads_dicts_stored_before_similarity() -> None:
    old = {"model": 0.0, "alpha": 0.0, "channel": 0.4, "topics": {}, "final": 0.4}

    assert ScoreBreakdown.from_dict(old) == ScoreBreakdown(channel=0.4)


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

    def model(c: RankCandidate, features: SimilarityFeatures | None) -> float:
        seen[c.video_id] = features
        return 0.0

    rank(
        [candidate("a"), candidate("b")],
        curation={},
        history=NO_HISTORY,
        embeddings={"a": axis(0)},
        rated_tiers=TIERS,
        model=model,
    )

    assert seen == {"a": similarity_features(axis(0), TIERS), "b": None}


def with_similarity(similarity: float) -> tuple[float, ...]:
    """A unit vector whose cosine similarity to `unit(0)` is `similarity`, orthogonal to
    every other `unit(i)` but the last."""
    return normalize(
        [similarity] + [0.0] * (EMBEDDING_DIMENSIONS - 2) + [math.sqrt(1 - similarity**2)]
    )


def unit(index: int) -> tuple[float, ...]:
    return tuple(1.0 if i == index else 0.0 for i in range(EMBEDDING_DIMENSIONS))


@pytest.mark.parametrize(
    ("weight", "similarity", "boost"),
    [
        (1.0, 1.0, 1.0),
        (1.0, 0.65, 0.5),
        (0.5, 0.65, 0.25),
        (-1.0, 0.65, -0.5),
        (1.0, 0.3, 0.0),
        (1.0, 0.1, 0.0),
        (-1.0, -0.9, 0.0),
    ],
)
def test_topic_boost(weight: float, similarity: float, boost: float) -> None:
    assert topic_boost(weight, similarity) == pytest.approx(boost)


def test_topic_boosts_by_name_leave_out_non_matching_topics() -> None:
    topics = [
        TopicVector("woodworking", 0.8, unit(0)),
        TopicVector("drama", -1.0, with_similarity(0.65)),
        TopicVector("cooking", 1.0, unit(1)),  # orthogonal: no boost
        TopicVector("off", 0.0, unit(0)),  # zero weight: no boost
    ]

    boosts = topic_boosts(unit(0), topics)

    assert boosts == {"woodworking": pytest.approx(0.8), "drama": pytest.approx(-0.5)}
    assert topic_boosts(None, topics) == {}


def test_rank_adds_topic_boosts_to_the_breakdown() -> None:
    topics = [TopicVector("woodworking", 1.0, unit(0)), TopicVector("drama", -0.6, unit(1))]
    videos = [candidate("plain"), candidate("wood"), candidate("drama"), candidate("unknown")]
    embeddings = {"plain": unit(2), "wood": with_similarity(0.65), "drama": unit(1)}

    scored = rank(videos, curation={}, history=NO_HISTORY, topics=topics, embeddings=embeddings)

    assert [item.candidate.video_id for item in scored] == ["wood", "plain", "unknown", "drama"]
    by_id = {item.candidate.video_id: item for item in scored}
    assert by_id["wood"].breakdown.topics == {"woodworking": pytest.approx(0.5)}
    assert by_id["drama"].breakdown.topics == {"drama": pytest.approx(-0.6)}
    assert by_id["plain"].breakdown.topics == {}
    assert by_id["unknown"].breakdown.topics == {}  # not enriched
    for item in scored:
        b = item.breakdown
        assert math.isclose(item.score, b.channel + sum(b.topics.values()))
