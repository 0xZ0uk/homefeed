"""The 1 to 10 rating scale (PLAN.md section 3).

A score is a whole number from 1 to 10, e.g. 4 or 9. Its numeric value is
`(score - 5.5) / 4.5`, so 1 is -1.0, 10 is +1.0 and the midpoint 5.5 (between 5 and 6) is
0. Pure functions only, shared by the API, ranker, trainer and insights.
"""

import math

MIN_SCORE = 1
MAX_SCORE = 10
_MIDPOINT = (MIN_SCORE + MAX_SCORE) / 2
_HALF_RANGE = (MAX_SCORE - MIN_SCORE) / 2

# A "good" video (the weekly good rate): above the midpoint.
GOOD_THRESHOLD = 6
# Top tier (the liked set for similarity features and related-video candidates).
TOP_TIER_THRESHOLD = 7
# Bottom tier (the disliked set).
BOTTOM_TIER_THRESHOLD = 4


def check_score(score: float) -> int:
    """`score` as a whole number. A float is accepted when it is exactly whole (7.0 is 7);
    a bool is not. Raises ValueError for scores outside 1 to 10 or with a fraction."""
    if isinstance(score, bool) or not isinstance(score, int | float):
        raise ValueError(f"Score {score!r} is not a number")
    if not math.isfinite(score) or not MIN_SCORE <= score <= MAX_SCORE:
        raise ValueError(f"Score {score!r} is not between 1 and 10")
    if score != int(score):
        raise ValueError(f"Score {score!r} is not a whole number")
    return int(score)


def score_value(score: int) -> float:
    """Numeric value in [-1, 1]: `(score - 5.5) / 4.5`."""
    return (check_score(score) - _MIDPOINT) / _HALF_RANGE


def value_score(value: float) -> float:
    """The point on the 1 to 10 scale whose value is `value` (clamped to [-1, 1]), to one
    decimal, e.g. to show a model's predicted rating value. Not a stored rating, so not
    necessarily whole."""
    clamped = min(1.0, max(-1.0, value))
    return round(_MIDPOINT + clamped * _HALF_RANGE, 1)


def is_good(score: int) -> bool:
    return score >= GOOD_THRESHOLD


def is_top_tier(score: int) -> bool:
    return score >= TOP_TIER_THRESHOLD


def is_bottom_tier(score: int) -> bool:
    return score <= BOTTOM_TIER_THRESHOLD
