"""Unit tests for the F5 exercise catalog (ai/exercise_catalog.py). OWNER: Shiri.

The catalog is hand-curated static data with no generator logic yet -- these tests guard its
structural integrity (every entry usable by a future selection algorithm) and catch silent drift
against the two contracts it must stay consistent with: the profile's EQUIPMENT vocabulary
(web/routes/profile.py) and the muscle_group vocabulary _program_recommendations already sums
volume over (ai/recommendations.py).
"""
import sys

import pytest

from ai.exercise_catalog import EQUIPMENT, EXERCISE_CATALOG, MUSCLE_GROUPS, PATTERNS


def test_catalog_size_is_in_the_planned_seed_range():
    assert 30 <= len(EXERCISE_CATALOG) <= 100


def test_every_entry_has_the_required_fields_with_correct_types():
    for entry in EXERCISE_CATALOG:
        assert isinstance(entry["name"], str) and entry["name"].strip() == entry["name"] and entry["name"]
        assert entry["muscle_group"] in MUSCLE_GROUPS
        assert entry["pattern"] in PATTERNS
        assert entry["equipment"] in EQUIPMENT
        assert isinstance(entry["is_compound"], bool)


def test_no_duplicate_exercise_names():
    names = [entry["name"] for entry in EXERCISE_CATALOG]
    assert len(names) == len(set(names))


def test_every_muscle_group_has_at_least_three_exercises():
    counts = {group: 0 for group in MUSCLE_GROUPS}
    for entry in EXERCISE_CATALOG:
        counts[entry["muscle_group"]] += 1
    thin = {group: count for group, count in counts.items() if count < 3}
    assert not thin, f"muscle groups with fewer than 3 catalog entries: {thin}"


def test_every_muscle_group_has_a_bodyweight_option_except_the_known_biceps_gap():
    """No standard bodyweight-only biceps movement exists; every other group has one.

    A bodyweight-only athlete (equipment == []) must still get a usable exercise for every
    muscle group a split day targets. Biceps is the one documented exception -- if this ever
    changes, update this test alongside the catalog rather than letting it drift silently.
    """
    groups_with_bodyweight = {
        entry["muscle_group"] for entry in EXERCISE_CATALOG if entry["equipment"] == "bodyweight"
    }
    missing = set(MUSCLE_GROUPS) - groups_with_bodyweight
    assert missing == {"biceps"}


def test_equipment_vocabulary_matches_the_profile_contract(web_app_module):
    """ai/ and web/ are separate containers with no shared import -- this guards against drift."""
    profile_equipment = sys.modules["routes.profile"].EQUIPMENT
    assert EQUIPMENT == profile_equipment


def test_chest_and_back_are_represented_for_the_existing_balance_check():
    """_program_recommendations special-cases chest/back volume ratio -- both must be sourceable."""
    muscle_groups_present = {entry["muscle_group"] for entry in EXERCISE_CATALOG}
    assert {"chest", "back"}.issubset(muscle_groups_present)


@pytest.mark.parametrize("pattern", PATTERNS)
def test_every_pattern_has_at_least_one_exercise(pattern):
    assert any(entry["pattern"] == pattern for entry in EXERCISE_CATALOG)
