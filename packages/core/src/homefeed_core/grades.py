"""The 30-grade tier-list scale (PLAN.md section 3).

Tiers F, D, C, B, A, S, each refined with --, -, (none), + or ++, ordered from F-- (index 0)
to S++ (index 29). A grade's numeric value is `-1 + 2 * index / 29`, so F-- is -1.0 and
S++ is +1.0. Pure functions only, shared by the API, ranker, trainer and insights.
"""

from typing import Literal, get_args

Grade = Literal[
    "F--", "F-", "F", "F+", "F++",
    "D--", "D-", "D", "D+", "D++",
    "C--", "C-", "C", "C+", "C++",
    "B--", "B-", "B", "B+", "B++",
    "A--", "A-", "A", "A+", "A++",
    "S--", "S-", "S", "S+", "S++",
]  # fmt: skip

TIERS = ("F", "D", "C", "B", "A", "S")
MODIFIERS = ("--", "-", "", "+", "++")

# Worst to best, index 0 to 29.
GRADES: tuple[Grade, ...] = get_args(Grade)

# A "good" video (the weekly good-tier rate): B-- or higher.
GOOD_THRESHOLD: Grade = "B--"
# Top tier (the liked set for similarity features and related-video candidates): A-- or higher.
TOP_TIER_THRESHOLD: Grade = "A--"
# Bottom tier (the disliked set): D++ or lower.
BOTTOM_TIER_THRESHOLD: Grade = "D++"

_INDEX: dict[str, int] = {grade: index for index, grade in enumerate(GRADES)}


def grade_index(grade: Grade) -> int:
    """Position on the scale, 0 (F--) to 29 (S++). Raises ValueError for unknown grades."""
    try:
        return _INDEX[grade]
    except KeyError:
        raise ValueError(f"Unknown grade {grade!r}") from None


def grade_value(grade: Grade) -> float:
    """Numeric value in [-1, 1]: `-1 + 2 * index / 29`."""
    return -1 + 2 * grade_index(grade) / (len(GRADES) - 1)


def is_good(grade: Grade) -> bool:
    return grade_index(grade) >= _INDEX[GOOD_THRESHOLD]


def is_top_tier(grade: Grade) -> bool:
    return grade_index(grade) >= _INDEX[TOP_TIER_THRESHOLD]


def is_bottom_tier(grade: Grade) -> bool:
    return grade_index(grade) <= _INDEX[BOTTOM_TIER_THRESHOLD]
