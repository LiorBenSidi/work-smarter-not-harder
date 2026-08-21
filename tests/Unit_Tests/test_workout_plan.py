"""Unit tests for the F5 workout generator (ai/workout_plan.py). OWNER: Shiri.

resolve_split_preference decides which split doctrine governs the week; day_focus_sequence turns
that into an ordered list of day-by-day focuses; generate_workout_days fills each day with
exercises from EXERCISE_CATALOG. All three stages are pure and deterministic -- no I/O, no
network calls, nothing to mock -- same as the rest of ai/ (see the module's own docstring). A
test that seemed to need mocking an external service would mean the design was wrong, not the
test, so none of these do.
"""
import sys

import pytest

from ai.workout_plan import (
    GOAL_ISOMETRIC_SETS_DURATION,
    GOAL_SETS_REPS,
    MIN_DAYS_FOR_SPLIT,
    SPLITS,
    day_focus_sequence,
    generate_workout_days,
    resolve_split_preference,
)


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


# --- day_focus_sequence ------------------------------------------------------------------
# resolve_split_preference passes an explicit split_preference through unchanged at ANY
# training_frequency -- it never validates that the frequency is high enough for that split to
# complete a full cycle. day_focus_sequence is what has to catch that pairing.

def test_ppl_with_insufficient_days_falls_back_to_full_body_at_one_day():
    """Regression: split_preference="push_pull_legs" + training_frequency=1 used to produce
    ["Push"] with Legs never appearing anywhere in the week."""
    assert day_focus_sequence("push_pull_legs", 1) == ["Full Body"]


def test_ppl_with_insufficient_days_falls_back_to_full_body_at_two_days():
    """Same bug at two days: the truncated cycle used to be ["Push", "Pull"] -- still no Legs."""
    assert day_focus_sequence("push_pull_legs", 2) == ["Full Body", "Full Body"]


def test_ppl_completes_a_full_cycle_at_its_minimum_day_count():
    assert day_focus_sequence("push_pull_legs", 3) == ["Push", "Pull", "Legs"]


def test_upper_lower_with_insufficient_days_falls_back_to_full_body():
    """Same class of bug, one day short for a 2-day cycle: ["Upper"] alone used to be possible."""
    assert day_focus_sequence("upper_lower", 1) == ["Full Body"]


def test_upper_lower_completes_a_full_cycle_at_its_minimum_day_count():
    assert day_focus_sequence("upper_lower", 2) == ["Upper", "Lower"]


@pytest.mark.parametrize("frequency", [3, 4, 5, 6, 7, 8, 14])
def test_push_pull_legs_focuses_never_appear_without_each_other(frequency):
    """The property the two regression tests above exist to protect, generalized: Push, Pull
    and Legs must appear together or not at all -- never a partial set -- across the whole
    legal training_frequency range (including the 8-14 tail, profile-legal but unrealistic)."""
    sequence = day_focus_sequence("push_pull_legs", frequency)
    focuses_present = {"Push", "Pull", "Legs"} & set(sequence)
    if focuses_present:
        assert focuses_present == {"Push", "Pull", "Legs"}


def test_full_body_repeats_the_same_focus_for_every_day():
    assert day_focus_sequence("full_body", 5) == ["Full Body"] * 5


def test_day_count_is_capped_at_seven_even_for_a_profile_legal_higher_frequency():
    assert len(day_focus_sequence("push_pull_legs", 14)) == 7


def test_zero_training_frequency_produces_an_empty_sequence():
    assert day_focus_sequence("push_pull_legs", 0) == []


@pytest.mark.parametrize(
    "bad_frequency", [None, "garbage", float("nan"), float("inf"), -1, True, {"$gt": ""}]
)
def test_unusable_training_frequency_produces_an_empty_sequence(bad_frequency):
    """Never guess a day count -- an unusable frequency means no days, not an invented one."""
    assert day_focus_sequence("push_pull_legs", bad_frequency) == []


def test_an_unrecognized_split_falls_back_to_the_full_body_cycle():
    """Defensive: must never crash on a split it doesn't recognize, even though its only real
    caller passes an already-resolved value from resolve_split_preference."""
    assert day_focus_sequence("cardio", 5) == ["Full Body"] * 5


def test_min_days_for_split_has_no_entry_for_full_body():
    """full_body can't truncate mid-cycle (every day is the same focus), so an entry for it
    here would be meaningless -- this catches a future refactor accidentally adding one."""
    assert "full_body" not in MIN_DAYS_FOR_SPLIT


# --- generate_workout_days ----------------------------------------------------------------

FULL_EQUIPMENT = ["barbell", "dumbbell", "bodyweight", "machine", "bands", "kettlebell", "pullup_bar"]
NO_MACHINE_EQUIPMENT = ["barbell", "dumbbell", "bodyweight"]


def test_every_day_has_the_contract_shape():
    days = generate_workout_days("full_body", 3, FULL_EQUIPMENT, "gain")
    assert len(days) == 3
    for expected_day_number, day in enumerate(days, start=1):
        assert set(day.keys()) == {"day", "focus", "exercises"}
        assert day["day"] == expected_day_number
        assert day["focus"] == "Full Body"
        assert isinstance(day["exercises"], list)
        for exercise in day["exercises"]:
            assert set(exercise.keys()) == {"name", "sets", "reps", "muscle_group"}
            assert isinstance(exercise["name"], str) and exercise["name"]
            assert isinstance(exercise["sets"], int)
            assert isinstance(exercise["reps"], str)
            assert isinstance(exercise["muscle_group"], str)


def test_focus_sequence_matches_day_focus_sequence_exactly():
    """generate_workout_days must walk the exact same sequence day_focus_sequence produces --
    the two are not allowed to drift apart."""
    for split, frequency in [("full_body", 3), ("upper_lower", 4), ("push_pull_legs", 7)]:
        days = generate_workout_days(split, frequency, FULL_EQUIPMENT, "maintain")
        assert [day["focus"] for day in days] == day_focus_sequence(split, frequency)


def test_full_body_covers_ten_muscle_groups_with_full_equipment():
    day = generate_workout_days("full_body", 1, FULL_EQUIPMENT, "gain")[0]
    groups = [exercise["muscle_group"] for exercise in day["exercises"]]
    assert len(groups) == 10
    assert groups.count("quads") == 2  # Squat + supplementary Leg Extension
    for group in ("hamstrings", "calves", "chest", "shoulders", "back", "biceps", "triceps", "core"):
        assert groups.count(group) == 1


def test_full_body_drops_only_the_supplementary_quads_slot_without_machine_equipment():
    """Regression: the supplementary isolation quads slot (Leg Extension) used to fall back to
    a second COMPOUND quads exercise when no isolation option was equipment-eligible, producing
    a literal duplicate exercise under a different label. It must skip instead."""
    day = generate_workout_days("full_body", 1, NO_MACHINE_EQUIPMENT, "gain")[0]
    assert len(day["exercises"]) == 9
    groups = [exercise["muscle_group"] for exercise in day["exercises"]]
    assert groups.count("quads") == 1
    assert groups.count("hamstrings") == 1  # hamstrings' only slot still falls back, unaffected


def test_no_exercise_is_ever_repeated_within_a_single_day():
    for split, frequency in [("full_body", 2), ("upper_lower", 2), ("push_pull_legs", 3)]:
        for day in generate_workout_days(split, frequency, FULL_EQUIPMENT, "gain"):
            names = [exercise["name"] for exercise in day["exercises"]]
            assert len(names) == len(set(names)), f"{split} {day['focus']}: {names}"


def test_upper_covers_exactly_six_muscle_groups():
    day = generate_workout_days("upper_lower", 2, FULL_EQUIPMENT, "maintain")[0]
    assert day["focus"] == "Upper"
    groups = {exercise["muscle_group"] for exercise in day["exercises"]}
    assert groups == {"chest", "shoulders", "back", "biceps", "triceps", "core"}


def test_lower_and_legs_cover_the_same_five_groups_with_full_equipment():
    lower_day = generate_workout_days("upper_lower", 2, FULL_EQUIPMENT, "maintain")[1]
    legs_day = generate_workout_days("push_pull_legs", 3, FULL_EQUIPMENT, "maintain")[2]
    assert lower_day["focus"] == "Lower"
    assert legs_day["focus"] == "Legs"
    for day in (lower_day, legs_day):
        assert len(day["exercises"]) == 5
        groups = [exercise["muscle_group"] for exercise in day["exercises"]]
        assert groups.count("quads") == 1
        assert groups.count("hamstrings") == 1
        assert groups.count("glutes") == 2  # general glutes slot + dedicated adductor/abductor slot
        assert groups.count("calves") == 1
        assert "core" not in groups


def test_lower_drops_only_the_adductor_abductor_slot_without_machine_equipment():
    day = generate_workout_days("upper_lower", 2, NO_MACHINE_EQUIPMENT, "maintain")[1]
    assert len(day["exercises"]) == 4
    groups = [exercise["muscle_group"] for exercise in day["exercises"]]
    assert groups.count("glutes") == 1  # only the general-glutes slot remains
    assert "Machine hip adductor" not in [e["name"] for e in day["exercises"]]
    assert "Machine hip abductor" not in [e["name"] for e in day["exercises"]]


def test_push_always_includes_a_core_exercise():
    for frequency in (3, 4, 5, 6, 7):
        for day in generate_workout_days("push_pull_legs", frequency, FULL_EQUIPMENT, "gain"):
            if day["focus"] == "Push":
                groups = [exercise["muscle_group"] for exercise in day["exercises"]]
                assert groups.count("core") == 1
                assert set(groups) == {"chest", "shoulders", "triceps", "core"}


def test_pull_never_includes_a_core_exercise():
    for frequency in (3, 4, 5, 6, 7):
        for day in generate_workout_days("push_pull_legs", frequency, FULL_EQUIPMENT, "gain"):
            if day["focus"] == "Pull":
                groups = [exercise["muscle_group"] for exercise in day["exercises"]]
                assert "core" not in groups
                assert set(groups) == {"back", "biceps", "shoulders"}


def test_core_appears_on_every_push_day_across_a_seven_day_ppl_week():
    """Regression: core placement was briefly first-occurrence-only, which clustered it on two
    consecutive days and capped it at 1x/week. The agreed rule is a fixed slot on Push, every
    time -- natural spacing across the PPL cycle, frequency that scales with training_frequency."""
    days = generate_workout_days("push_pull_legs", 7, FULL_EQUIPMENT, "gain")
    push_days = [day for day in days if day["focus"] == "Push"]
    pull_and_legs_days = [day for day in days if day["focus"] in ("Pull", "Legs")]
    assert len(push_days) == 3  # days 1, 4, 7
    for day in push_days:
        assert any(exercise["muscle_group"] == "core" for exercise in day["exercises"])
    for day in pull_and_legs_days:
        assert not any(exercise["muscle_group"] == "core" for exercise in day["exercises"])


def test_bodyweight_only_pull_skips_biceps_and_shoulders_gracefully():
    """Both documented catalog gaps (no bodyweight biceps, no bodyweight pull-pattern
    shoulders) apply to Pull at once -- must degrade to just the back exercise, never crash."""
    day = generate_workout_days("push_pull_legs", 3, [], "lose")[1]
    assert day["focus"] == "Pull"
    groups = [exercise["muscle_group"] for exercise in day["exercises"]]
    assert groups == ["back"]


def test_push_day_uses_the_exact_named_exercises_for_chest_shoulders_and_triceps():
    day = generate_workout_days("push_pull_legs", 3, FULL_EQUIPMENT, "gain")[0]
    assert day["focus"] == "Push"
    names = [exercise["name"] for exercise in day["exercises"]]
    assert names == [
        "Barbell bench press", "Incline dumbbell press", "Dumbbell flye",
        "Barbell overhead press", "Dumbbell front raise", "Dumbbell lateral raise",
        "Barbell close-grip bench press", "Triceps rope pushdown (Cable)",
        "Plank",
    ]


def test_pull_day_uses_the_exact_named_exercises_for_back_and_biceps_but_not_shoulders():
    """shoulders is one of the muscle groups that gets a named list on Upper and Push, but Pull
    must keep it at a single auto-selected pick -- doubling shoulder volume on both Push AND
    Pull in the same week was the explicit reason to hold it back here."""
    day = generate_workout_days("push_pull_legs", 3, FULL_EQUIPMENT, "gain")[1]
    assert day["focus"] == "Pull"
    names = [exercise["name"] for exercise in day["exercises"]]
    assert names[:5] == [
        "Pull-up", "Lat pulldown", "Seated cable row",
        "Barbell curl", "Dumbbell hammer curl",
    ]
    assert len(names) == 6  # the 5 named exercises plus exactly one auto-selected shoulders pick
    groups = [exercise["muscle_group"] for exercise in day["exercises"]]
    assert groups.count("shoulders") == 1


def test_upper_day_uses_the_exact_named_exercises_for_all_five_groups():
    day = generate_workout_days("upper_lower", 2, FULL_EQUIPMENT, "gain")[0]
    assert day["focus"] == "Upper"
    names = [exercise["name"] for exercise in day["exercises"]]
    assert names == [
        "Barbell bench press", "Incline dumbbell press", "Dumbbell flye",
        "Barbell overhead press", "Dumbbell front raise", "Dumbbell lateral raise",
        "Pull-up", "Lat pulldown", "Seated cable row",
        "Barbell curl", "Dumbbell hammer curl",
        "Barbell close-grip bench press", "Triceps rope pushdown (Cable)",
        "Plank",
    ]


def test_bodyweight_only_push_falls_back_to_one_auto_selected_exercise_per_group():
    """No named Push exercise is bodyweight equipment (all barbell/machine/dumbbell/cable), so
    the fallback must degrade chest/shoulders/triceps to _pick's normal single auto-selection
    rather than leaving them empty -- an equipment-starved athlete still gets a full day."""
    day = generate_workout_days("push_pull_legs", 3, [], "gain")[0]
    assert day["focus"] == "Push"
    groups = [exercise["muscle_group"] for exercise in day["exercises"]]
    assert groups.count("chest") == 1
    assert groups.count("shoulders") == 1
    assert groups.count("triceps") == 1
    assert groups.count("core") == 1
    assert len(groups) == 4
    names = [exercise["name"] for exercise in day["exercises"]]
    assert "Push-up" in names
    assert "Pike push-up" in names


def test_bodyweight_only_upper_falls_back_per_group_and_still_skips_biceps():
    """Biceps has zero bodyweight entries anywhere in the catalog -- a pre-existing gap,
    unrelated to this feature -- so the fallback must not invent one. Chest/shoulders/back/
    triceps each degrade to one auto-selected exercise instead of the named list."""
    day = generate_workout_days("upper_lower", 2, [], "gain")[0]
    assert day["focus"] == "Upper"
    groups = [exercise["muscle_group"] for exercise in day["exercises"]]
    assert "biceps" not in groups
    for group in ("chest", "shoulders", "back", "triceps", "core"):
        assert groups.count(group) == 1
    assert len(groups) == 5


def test_every_named_multi_exercise_actually_exists_in_the_catalog():
    """The Upper/Push/Pull named lists are hand-typed strings, not derived from the catalog --
    if a referenced exercise is ever renamed (as happened to two entries in #535), this fails
    with a clear assertion instead of a raw KeyError deep inside _select_named_exercises."""
    from ai.exercise_catalog import EXERCISE_CATALOG

    catalog_names = {entry["name"] for entry in EXERCISE_CATALOG}
    named_exercises = [
        "Barbell bench press", "Incline dumbbell press", "Dumbbell flye",
        "Barbell overhead press", "Dumbbell front raise", "Dumbbell lateral raise",
        "Pull-up", "Lat pulldown", "Seated cable row",
        "Barbell curl", "Dumbbell hammer curl",
        "Barbell close-grip bench press", "Triceps rope pushdown (Cable)",
    ]
    for name in named_exercises:
        assert name in catalog_names, f"{name!r} is not in EXERCISE_CATALOG"


@pytest.mark.parametrize(("goal", "sets", "reps"), [
    ("gain", 4, "6-8"),
    ("maintain", 3, "8-12"),
    ("lose", 3, "12-15"),
])
def test_rep_based_exercises_use_the_goal_sets_reps_table(goal, sets, reps):
    """Lower (not Upper) -- Upper includes a core slot that always resolves to Plank
    (is_isometric=True), whose "reps" is a duration string, not a rep range. Lower never
    includes core, so every exercise here is rep-based, no filtering needed."""
    day = generate_workout_days("upper_lower", 2, FULL_EQUIPMENT, goal)[1]
    for exercise in day["exercises"]:
        assert exercise["sets"] == sets
        assert exercise["reps"] == reps


@pytest.mark.parametrize("goal", ["gain", "maintain", "lose"])
def test_isometric_exercises_get_a_duration_not_a_rep_range(goal):
    """Plank must use GOAL_ISOMETRIC_SETS_DURATION, never GOAL_SETS_REPS -- a rep range like
    "6-8" is meaningless for a held position. Asserted against the actual table, not a
    hardcoded copy of its values, so a future change to the table can't silently drift from
    what this test expects."""
    day = generate_workout_days("push_pull_legs", 3, FULL_EQUIPMENT, goal)[0]
    assert day["focus"] == "Push"
    plank = next(e for e in day["exercises"] if e["name"] == "Plank")
    expected_sets, expected_duration = GOAL_ISOMETRIC_SETS_DURATION[goal]
    assert plank["sets"] == expected_sets
    assert plank["reps"] == expected_duration
    assert plank["reps"] not in {reps for _, reps in GOAL_SETS_REPS.values()}


def test_an_unusable_training_frequency_produces_no_days():
    assert generate_workout_days("push_pull_legs", None, FULL_EQUIPMENT, "gain") == []


def test_zero_training_frequency_produces_no_days():
    assert generate_workout_days("push_pull_legs", 0, FULL_EQUIPMENT, "gain") == []


def test_an_unrecognized_split_falls_back_to_full_body_and_never_crashes():
    days = generate_workout_days("cardio", 3, FULL_EQUIPMENT, "gain")
    assert [day["focus"] for day in days] == ["Full Body", "Full Body", "Full Body"]


@pytest.mark.parametrize("bad_goal", ["bulk", "", None, 123, {"$gt": ""}, ["gain"]])
def test_an_unrecognized_goal_falls_back_to_maintain(bad_goal):
    day = generate_workout_days("full_body", 1, FULL_EQUIPMENT, bad_goal)[0]
    non_isometric = [e for e in day["exercises"] if e["reps"] in ("6-8", "8-12", "12-15")]
    assert all(e["sets"] == 3 and e["reps"] == "8-12" for e in non_isometric)


@pytest.mark.parametrize("bad_equipment", [None, "barbell", 123, {"$gt": ""}, [{"$gt": ""}], [123, None]])
def test_an_unusable_equipment_argument_degrades_to_bodyweight_only_never_crashes(bad_equipment):
    days = generate_workout_days("push_pull_legs", 3, bad_equipment, "gain")
    assert len(days) == 3
    pull_day = days[1]
    assert [e["muscle_group"] for e in pull_day["exercises"]] == ["back"]
