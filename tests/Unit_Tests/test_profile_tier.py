"""`derive_tier` — PROPOSAL-v2 §3's Beginner / Intermediate / Advanced structure (#528 item 3).

The tier is *derived*, never stored, so these tests are about one question: does the label match what
the athlete has actually filled in? A stored tier could drift from its profile; a derived one cannot,
and that property is what the tests below pin.

Nothing is gated on the tier -- every output stays available to every user -- so a "beginner" label
withholds nothing. That is asserted at the route level in the integration tests, not here.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "web"))

from routes.profile import derive_tier  # noqa: E402


def test_a_minimum_profile_is_a_beginner():
    """§3's Beginner provides age, gender, height, weight and a goal -- nothing optional."""
    assert derive_tier({"age": 27, "gender": "male", "height": 180,
                        "weight": 78, "goal": "maintain", "training_frequency": 4}) == "beginner"


@pytest.mark.parametrize("optional_field,value", [
    ("equipment", ["bands"]),
    ("split_preference", "upper_lower"),
])
def test_an_optional_planning_input_makes_an_intermediate(optional_field, value):
    """Equipment and split shape the generated programme without unlocking a new output."""
    profile = {"age": 27, "goal": "maintain", "training_frequency": 4, optional_field: value}
    assert derive_tier(profile) == "intermediate"


def test_a_weekly_programme_makes_an_advanced():
    """The Advanced tier's own "provide your workout program" input (#566) -- the one field that
    unlocks a genuinely different output, the muscle-group balance analysis."""
    assert derive_tier({"age": 27, "goal": "gain", "training_program": {"chest": 12, "back": 8}}) == "advanced"


def test_a_programme_outranks_the_optional_planning_inputs():
    """Someone who filled in everything is Advanced, not Intermediate -- the highest tier they qualify
    for, never the first one matched."""
    profile = {"age": 27, "goal": "gain", "equipment": ["bands"],
               "split_preference": "upper_lower", "training_program": {"chest": 12}}
    assert derive_tier(profile) == "advanced"


def test_a_zero_volume_programme_still_counts_as_advanced():
    """`{"back": 0}` is a real, deliberately logged answer (#583) -- the athlete entered a programme.
    Truthiness on the dict itself, never on the sets inside it, is what keeps this true."""
    assert derive_tier({"age": 27, "goal": "gain", "training_program": {"back": 0, "chest": 12}}) == "advanced"


@pytest.mark.parametrize("empty", [{}, None, [], ""])
def test_an_empty_programme_is_not_an_advanced(empty):
    """An absent or emptied programme demotes the athlete rather than stranding them in a tier whose
    output (the balance analysis) has nothing to analyse."""
    assert derive_tier({"age": 27, "goal": "gain", "training_program": empty}) == "beginner"


@pytest.mark.parametrize("not_a_profile", [None, "beginner", 42, [], ["advanced"]])
def test_no_profile_has_no_tier(not_a_profile):
    """None, not "beginner": a user who has saved nothing has not been placed in a tier at all, and
    the UI renders no tier line rather than mislabelling them."""
    assert derive_tier(not_a_profile) is None


def test_an_empty_dict_profile_is_a_beginner_not_none():
    """A saved-but-bare profile IS a profile -- distinct from having none at all."""
    assert derive_tier({}) == "beginner"
