import itertools
import math

import pytest

from homefeed_core.grades import (
    BOTTOM_TIER_THRESHOLD,
    GOOD_THRESHOLD,
    GRADES,
    MODIFIERS,
    TIERS,
    TOP_TIER_THRESHOLD,
    Grade,
    grade_index,
    grade_value,
    is_bottom_tier,
    is_good,
    is_top_tier,
    nearest_grade,
)

EXPECTED_ORDER = [
    "F--", "F-", "F", "F+", "F++",
    "D--", "D-", "D", "D+", "D++",
    "C--", "C-", "C", "C+", "C++",
    "B--", "B-", "B", "B+", "B++",
    "A--", "A-", "A", "A+", "A++",
    "S--", "S-", "S", "S+", "S++",
]  # fmt: skip


def test_grade_order_is_tiers_times_modifiers() -> None:
    assert list(GRADES) == EXPECTED_ORDER
    assert list(GRADES) == [t + m for t, m in itertools.product(TIERS, MODIFIERS)]
    assert len(set(GRADES)) == 30


@pytest.mark.parametrize(("index", "grade"), list(enumerate(EXPECTED_ORDER)))
def test_value_for_every_grade(index: int, grade: Grade) -> None:
    assert grade_index(grade) == index
    assert math.isclose(grade_value(grade), -1 + 2 * index / 29)


def test_value_endpoints_and_monotonic() -> None:
    assert grade_value("F--") == -1.0
    assert grade_value("S++") == 1.0
    values = [grade_value(g) for g in GRADES]
    assert values == sorted(values)
    assert len(set(values)) == 30


def test_unknown_grade_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown grade"):
        grade_value("Z")  # type: ignore[arg-type]


def test_thresholds() -> None:
    assert (GOOD_THRESHOLD, TOP_TIER_THRESHOLD, BOTTOM_TIER_THRESHOLD) == ("B--", "A--", "D++")


@pytest.mark.parametrize("grade", EXPECTED_ORDER)
def test_good_is_b_minus_minus_or_higher(grade: Grade) -> None:
    assert is_good(grade) == (grade[0] in "BAS")


@pytest.mark.parametrize("grade", EXPECTED_ORDER)
def test_top_tier_is_a_minus_minus_or_higher(grade: Grade) -> None:
    assert is_top_tier(grade) == (grade[0] in "AS")


@pytest.mark.parametrize("grade", EXPECTED_ORDER)
def test_bottom_tier_is_d_plus_plus_or_lower(grade: Grade) -> None:
    assert is_bottom_tier(grade) == (grade[0] in "FD")


def test_threshold_boundaries() -> None:
    assert not is_good("C++") and is_good("B--")
    assert not is_top_tier("B++") and is_top_tier("A--")
    assert is_bottom_tier("D++") and not is_bottom_tier("C--")


@pytest.mark.parametrize("grade", GRADES)
def test_nearest_grade_inverts_grade_value(grade: Grade) -> None:
    assert nearest_grade(grade_value(grade)) == grade


def test_nearest_grade_rounds_and_clamps() -> None:
    assert nearest_grade(0.0) == "C++"  # between C++ and B--, index 14.5 rounds to even
    assert nearest_grade(grade_value("B+") + 0.01) == "B+"
    assert nearest_grade(-5.0) == "F--"
    assert nearest_grade(5.0) == "S++"
