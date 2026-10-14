import math

import pytest

from homefeed_core.scores import (
    BOTTOM_TIER_THRESHOLD,
    GOOD_THRESHOLD,
    MAX_SCORE,
    MIN_SCORE,
    TOP_TIER_THRESHOLD,
    check_score,
    is_bottom_tier,
    is_good,
    is_top_tier,
    score_value,
    value_score,
)

ALL_SCORES = list(range(1, 11))


def test_scale_is_one_to_ten() -> None:
    assert (MIN_SCORE, MAX_SCORE) == (1, 10)


@pytest.mark.parametrize("score", ALL_SCORES)
def test_check_score_accepts_whole_scores(score: int) -> None:
    assert check_score(score) == score
    assert isinstance(check_score(score), int)


def test_check_score_accepts_whole_floats_as_ints() -> None:
    result = check_score(7.0)
    assert result == 7 and isinstance(result, int)
    assert check_score(10.0) == 10 and check_score(1.0) == 1


@pytest.mark.parametrize("score", [0, 11, -3, 0.9, 10.1, 11.0, math.nan, math.inf, -math.inf])
def test_check_score_rejects_out_of_range(score: float) -> None:
    with pytest.raises(ValueError, match="between 1 and 10"):
        check_score(score)


@pytest.mark.parametrize("score", [7.5, 4.25, 9.9, 1.01, 6.9999])
def test_check_score_rejects_fractions(score: float) -> None:
    with pytest.raises(ValueError, match="not a whole number"):
        check_score(score)


@pytest.mark.parametrize("score", [True, False, "7", None])
def test_check_score_rejects_non_numbers(score: object) -> None:
    with pytest.raises(ValueError, match="not a number"):
        check_score(score)  # type: ignore[arg-type]


def test_value_endpoints_and_monotonic() -> None:
    assert score_value(1) == -1.0
    assert score_value(10) == 1.0
    assert score_value(5) == pytest.approx(-0.5 / 4.5)
    assert score_value(6) == pytest.approx(0.5 / 4.5)
    values = [score_value(s) for s in ALL_SCORES]
    assert values == sorted(values)
    assert len(set(values)) == len(ALL_SCORES)


def test_value_score_shows_a_prediction_to_one_decimal() -> None:
    assert value_score(0.0) == 5.5
    assert value_score(score_value(7) + 0.001) == 7.0
    assert value_score(-5.0) == 1.0
    assert value_score(5.0) == 10.0


@pytest.mark.parametrize("score", ALL_SCORES)
def test_value_score_inverts_score_value(score: int) -> None:
    assert value_score(score_value(score)) == score


def test_thresholds() -> None:
    assert (GOOD_THRESHOLD, TOP_TIER_THRESHOLD, BOTTOM_TIER_THRESHOLD) == (6, 7, 4)


def test_threshold_boundaries() -> None:
    assert not is_good(5) and is_good(6)
    assert not is_top_tier(6) and is_top_tier(7)
    assert is_bottom_tier(4) and not is_bottom_tier(5)
