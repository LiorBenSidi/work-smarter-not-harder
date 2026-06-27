"""TDD unit tests for the calorie recommendation (F4) — Mifflin-St Jeor.

Spec-first: every expected value below is computed from the *published formula* (verifiable by
hand), not read off the implementation — so the tests are independent of how the code is written.

  BMR (Mifflin-St Jeor):
    male:   10*kg + 6.25*cm - 5*age + 5
    female: 10*kg + 6.25*cm - 5*age - 161
  TDEE = BMR * activity_factor ; goal adjusts the maintenance target.
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("calories", str(ROOT / "ai" / "calories.py"))
calories = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(calories)


def test_bmr_male_known_value():
    # 10*80 + 6.25*180 - 5*30 + 5 = 800 + 1125 - 150 + 5 = 1780
    assert calories.mifflin_st_jeor_bmr(80, 180, 30, "male") == pytest.approx(1780.0)


def test_bmr_female_known_value():
    # 10*60 + 6.25*165 - 5*25 - 161 = 600 + 1031.25 - 125 - 161 = 1345.25
    assert calories.mifflin_st_jeor_bmr(60, 165, 25, "female") == pytest.approx(1345.25)


def test_sex_is_case_insensitive():
    assert calories.mifflin_st_jeor_bmr(80, 180, 30, "MALE") == calories.mifflin_st_jeor_bmr(80, 180, 30, "male")


def test_unmapped_sex_uses_neutral_midpoint():
    male = calories.mifflin_st_jeor_bmr(80, 180, 30, "male")        # 1780
    female = calories.mifflin_st_jeor_bmr(80, 180, 30, "female")    # 1614
    other = calories.mifflin_st_jeor_bmr(80, 180, 30, "nonbinary")  # neutral -> 1697
    assert female < other < male


def test_maintenance_target_applies_activity_factor():
    # BMR 1780 * 1.55 (moderate) = 2759.0 ; goal "maintain" -> +0
    assert calories.daily_calorie_target(80, 180, 30, "male", "moderate", "maintain") == 2759


def test_lose_goal_applies_a_deficit():
    base = calories.daily_calorie_target(80, 180, 30, "male", "moderate", "maintain")
    assert calories.daily_calorie_target(80, 180, 30, "male", "moderate", "lose") == base - 500


def test_gain_goal_applies_a_surplus():
    base = calories.daily_calorie_target(80, 180, 30, "male", "moderate", "maintain")
    assert calories.daily_calorie_target(80, 180, 30, "male", "moderate", "gain") == base + 500


def test_target_is_floored_at_a_safe_minimum():
    # tiny person + aggressive deficit must never drop below the safety floor
    assert calories.daily_calorie_target(40, 150, 80, "female", "sedentary", "lose") == calories.MIN_SAFE_KCAL


@pytest.mark.parametrize("bad_weight", [0, -5, "heavy", None])
def test_rejects_invalid_weight(bad_weight):
    with pytest.raises((ValueError, TypeError)):
        calories.daily_calorie_target(bad_weight, 180, 30, "male", "moderate", "maintain")


def test_rejects_unknown_activity_level():
    with pytest.raises(ValueError):
        calories.daily_calorie_target(80, 180, 30, "male", "teleporting", "maintain")


def test_rejects_unknown_goal():
    with pytest.raises(ValueError):
        calories.daily_calorie_target(80, 180, 30, "male", "moderate", "ascend")
