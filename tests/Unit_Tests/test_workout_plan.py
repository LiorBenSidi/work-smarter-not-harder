"""Unit tests for the F5 split-day resolution (ai/workout_plan.py). OWNER: Shiri.

resolve_split_preference is the first stage of the workout generator: it decides which split
doctrine governs the week, before any exercise gets picked. These tests pin the exact threshold
rule and the plan-contract output shape (both agreed with Lior on #410) and guard against drift
from the profile's SPLITS contract.
"""
import sys

import pytest

from ai.workout_plan import SPLITS, resolve_split_preference


@pytest.mark.parametrize("split", ["full_body", "upper_lower", "push_pull_legs"])
@pytest.mark.parametrize("frequency", [0, 3, 4, 5, 6, 7, 14])
def test_an_explicit_split_passes_through_unchanged_regardless_of_frequency(split, frequency):
    assert resolve_split_preference(split, frequency) == {"split": split, "days": None}


@pytest.mark.parametrize("frequency", [0, 1, 2, 3])
def test_no_preference_at_or_below_three_days_resolves_to_full_body_alone(frequency):
    assert resolve_split_preference("no_preference", frequency) == {
        "split": "full_body",
        "days": None,
    }


def test_no_preference_at_four_days_offers_full_body_and_upper_lower():
    assert resolve_split_preference("no_preference", 4) == {
        "split_options": ["full_body", "upper_lower"]
    }


def test_no_preference_at_five_days_offers_upper_lower_and_push_pull_legs():
    assert resolve_split_preference("no_preference", 5) == {
        "split_options": ["upper_lower", "push_pull_legs"]
    }


@pytest.mark.parametrize("frequency", [6, 7])
def test_no_preference_at_six_or_seven_days_resolves_to_push_pull_legs_alone(frequency):
    assert resolve_split_preference("no_preference", frequency) == {
        "split": "push_pull_legs",
        "days": None,
    }


@pytest.mark.parametrize("frequency", [8, 10, 14])
def test_no_preference_above_seven_days_still_resolves_to_push_pull_legs_alone(frequency):
    """training_frequency is profile-legal up to 14 even though a week only has 7 days --
    the >=6 bucket must not crash or invent a fifth split for the unrealistic tail."""
    assert resolve_split_preference("no_preference", frequency) == {
        "split": "push_pull_legs",
        "days": None,
    }


@pytest.mark.parametrize(
    "bad_split", ["cardio", "", None, 123, {"$gt": ""}, ["full_body"]]
)
def test_an_unrecognized_split_preference_falls_back_to_the_no_preference_resolution(bad_split):
    """Bad/injected split_preference must never crash the engine -- treat it like no_preference."""
    assert resolve_split_preference(bad_split, 4) == {
        "split_options": ["full_body", "upper_lower"]
    }


@pytest.mark.parametrize(
    "bad_frequency", [None, "four", float("nan"), float("inf"), -1, True, {"$gt": ""}]
)
def test_an_unusable_training_frequency_defaults_to_full_body(bad_frequency):
    assert resolve_split_preference("no_preference", bad_frequency) == {
        "split": "full_body",
        "days": None,
    }


def test_resolved_results_carry_a_days_placeholder_and_no_split_options_key():
    for split in ("full_body", "upper_lower", "push_pull_legs"):
        result = resolve_split_preference(split, 4)
        assert set(result.keys()) == {"split", "days"}
        assert result["split"] == split
        assert result["days"] is None


def test_ambiguous_results_only_ever_contain_two_valid_splits_and_no_split_key():
    for frequency in (4, 5):
        result = resolve_split_preference("no_preference", frequency)
        assert set(result.keys()) == {"split_options"}
        options = result["split_options"]
        assert isinstance(options, list)
        assert len(options) == 2
        assert all(option in SPLITS for option in options)


def test_splits_vocabulary_matches_the_profile_contract(web_app_module):
    """ai/ and web/ are separate containers with no shared import -- this guards against drift."""
    profile_splits = sys.modules["routes.profile"].SPLITS
    assert SPLITS == profile_splits
