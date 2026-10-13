"""The 1 to 10 rating scale (PLAN.md section 3).

A score is a number from 1.0 to 10.0 in steps of 0.1, e.g. 4.2 or 9.9. Its numeric value
is `(score - 5.5) / 4.5`, so 1.0 is -1.0, 10.0 is +1.0 and the midpoint 5.5 is 0. Pure
functions only, shared by the API, ranker, trainer and insights.
"""

import math

MIN_SCORE = 1.0
MAX_SCORE = 10.0
_MIDPOINT = (MIN_SCORE + MAX_SCORE) / 2
_HALF_RANGE = (MAX_SCORE - MIN_SCORE) / 2

# A "good" video (the weekly good rate): above the midpoint.
GOOD_THRESHOLD = 5.5
# Top tier (the liked set for similarity features and related-video candidates).
TOP_TIER_THRESHOLD = 7.0
# Bottom tier (the disliked set).
BOTTOM_TIER_THRESHOLD = 4.0


def check_score(score: float) -> float:
    """`score` rounded to its one decimal. Raises ValueError for scores outside 1 to 10
    or with more than one decimal."""
    if not math.isfinite(score) or not MIN_SCORE <= score <= MAX_SCORE:
        raise ValueError(f"Score {score!r} is not between 1 and 10")
    rounded = round(score, 1)
    if not math.isclose(score, rounded, abs_tol=1e-9):
        raise ValueError(f"Score {score!r} has more than one decimal")
    return rounded


def score_value(score: float) -> float:
    """Numeric value in [-1, 1]: `(score - 5.5) / 4.5`."""
    return (check_score(score) - _MIDPOINT) / _HALF_RANGE


def value_score(value: float) -> float:
    """The score whose value is closest to `value` (clamped to [-1, 1]), e.g. to show a
    predicted rating value as a score."""
    clamped = min(1.0, max(-1.0, value))
    return round(_MIDPOINT + clamped * _HALF_RANGE, 1)


def score_bucket(score: float) -> int:
    """The whole score, 1 to 10, that `score` rounds to (halves round up: 6.5 is 7)."""
    return math.floor(round(score, 1) + 0.5)


def is_good(score: float) -> bool:
    return score >= GOOD_THRESHOLD


def is_top_tier(score: float) -> bool:
    return score >= TOP_TIER_THRESHOLD


def is_bottom_tier(score: float) -> bool:
    return score <= BOTTOM_TIER_THRESHOLD
