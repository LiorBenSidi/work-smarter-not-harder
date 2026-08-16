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
        assert isinstance(entry["is_isometric"], bool)


def test_plank_is_the_only_isometric_entry():
    """is_isometric is True only for an unambiguous static hold. Dual-mode movements commonly
    done for reps in practice (glute bridges, Pallof press) are deliberately False, not "fixed"
    to True -- if that changes, update this test alongside the catalog, not silently."""
    isometric_names = {entry["name"] for entry in EXERCISE_CATALOG if entry["is_isometric"]}
    assert isometric_names == {"Plank"}


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


def test_pull_pattern_shoulders_have_no_bodyweight_option_documented_gap():
    """No standard bodyweight-only rear-delt/pull-pattern shoulder movement exists in the
    catalog -- discovered while designing generate_workout_days' Pull day (a bodyweight-only
    Pull day skips its shoulders slot entirely). Shoulders as a whole DOES have a bodyweight
    option (Pike push-up, pattern="push"), so the broader per-muscle-group bodyweight check
    above doesn't catch this -- it's specific to the (shoulders, pull) combination. Second
    documented equipment gap alongside biceps -- if this ever changes, update this test
    alongside the catalog rather than letting it drift silently.
    """
    pull_shoulder_entries = [
        entry
        for entry in EXERCISE_CATALOG
        if entry["muscle_group"] == "shoulders" and entry["pattern"] == "pull"
    ]
    assert pull_shoulder_entries  # sanity: the group itself isn't empty
    assert not any(entry["equipment"] == "bodyweight" for entry in pull_shoulder_entries)


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
