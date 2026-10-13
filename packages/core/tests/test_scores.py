import math

import pytest

from homefeed_core.scores import (
    BOTTOM_TIER_THRESHOLD,
    GOOD_THRESHOLD,
    TOP_TIER_THRESHOLD,
    check_score,
    is_bottom_tier,
    is_good,
    is_top_tier,
    score_bucket,
    score_value,
    value_score,
)

ALL_SCORES = [n / 10 for n in range(10, 101)]


def test_check_score_accepts_one_decimal() -> None:
    assert check_score(1) == 1.0
    assert check_score(9.9) == 9.9
    assert check_score(4.2) == 4.2
    assert check_score(10.0) == 10.0
    assert check_score(0.1 + 0.2 + 6.4) == 6.7  # float noise is rounded away


@pytest.mark.parametrize("score", [0.9, 0.0, -3.0, 10.1, 11.0, math.nan, math.inf])
def test_check_score_rejects_out_of_range(score: float) -> None:
    with pytest.raises(ValueError, match="between 1 and 10"):
        check_score(score)


@pytest.mark.parametrize("score", [4.25, 9.99, 1.01])
def test_check_score_rejects_extra_decimals(score: float) -> None:
    with pytest.raises(ValueError, match="more than one decimal"):
        check_score(score)


def test_value_endpoints_and_monotonic() -> None:
    assert score_value(1.0) == -1.0
    assert score_value(5.5) == 0.0
    assert score_value(10.0) == 1.0
    values = [score_value(s) for s in ALL_SCORES]
    assert values == sorted(values)
    assert len(set(values)) == len(ALL_SCORES)


@pytest.mark.parametrize("score", ALL_SCORES)
def test_value_score_inverts_score_value(score: float) -> None:
    assert value_score(score_value(score)) == score


def test_value_score_rounds_and_clamps() -> None:
    assert value_score(0.0) == 5.5
    assert value_score(score_value(7.3) + 0.001) == 7.3
    assert value_score(-5.0) == 1.0
    assert value_score(5.0) == 10.0


def test_thresholds() -> None:
    assert (GOOD_THRESHOLD, TOP_TIER_THRESHOLD, BOTTOM_TIER_THRESHOLD) == (5.5, 7.0, 4.0)


def test_threshold_boundaries() -> None:
    assert not is_good(5.4) and is_good(5.5)
    assert not is_top_tier(6.9) and is_top_tier(7.0)
    assert is_bottom_tier(4.0) and not is_bottom_tier(4.1)


@pytest.mark.parametrize(
    ("score", "bucket"),
    [(1.0, 1), (1.4, 1), (1.5, 2), (6.5, 7), (6.4, 6), (9.4, 9), (9.5, 10), (10.0, 10)],
)
def test_score_bucket_rounds_half_up(score: float, bucket: int) -> None:
    assert score_bucket(score) == bucket
