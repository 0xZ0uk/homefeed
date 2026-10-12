import math
from typing import Any

import pytest

from homefeed_core.grades import grade_value
from homefeed_core.ranker import (
    CHANNEL_PRIOR_WEIGHT,
    ChannelCuration,
    DurationBounds,
    FilterReason,
    History,
    RankCandidate,
    ScoreBreakdown,
    alpha,
    channel_score,
    filter_reason,
    rank,
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

    for model in (None, lambda _: 0.7):
        for item in rank(videos, curation=curation, history=history, model=model):
            b = item.breakdown
            parts = b.alpha * b.model + b.channel + sum(b.topics.values())
            assert math.isclose(item.score, parts)
            assert b.to_dict()["final"] == item.score


def test_breakdown_with_model_and_topics() -> None:
    breakdown = ScoreBreakdown(model=0.5, alpha=0.4, channel=0.1, topics={"woodworking": 0.2})

    assert breakdown.final == pytest.approx(0.2 + 0.1 + 0.2)
    assert breakdown.to_dict() == {
        "model": 0.5,
        "alpha": 0.4,
        "channel": 0.1,
        "topics": {"woodworking": 0.2},
        "final": breakdown.final,
    }
