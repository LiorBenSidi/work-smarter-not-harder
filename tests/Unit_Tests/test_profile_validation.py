"""Unit tests for F2 profile validation. OWNER: Lior.

A profile is valid only when it is a JSON object with the right field TYPES and ranges. Non-primitive
values (injection objects), wrong types, bools-as-numbers, and out-of-range values are rejected by
`validate_profile` before any query runs.
"""
import sys

import pytest


@pytest.fixture
def validate(web_app_module):
    return sys.modules["routes.profile"].validate_profile


def _ok():
    return {"age": 30, "gender": "male", "height": 180, "weight": 80, "goal": "maintain", "training_frequency": 3}


def test_accepts_a_valid_profile(validate):
    """An ordinary profile passes with its values intact, so the gate does not turn away real users."""
    out = validate(_ok())
    assert out["age"] == 30
    assert out["goal"] == "maintain"
    assert out["training_frequency"] == 3


def test_accepts_float_height_and_weight(validate):
    """Height and weight are genuine measurements, so fractional values are kept rather than forced to whole numbers a user never entered."""
    p = _ok()
    p["height"], p["weight"] = 175.5, 72.4
    out = validate(p)
    assert out["height"] == 175.5
    assert out["weight"] == 72.4


@pytest.mark.parametrize("bad", [None, "x"])   # one absent, one wrong-type — same branch, distinct shapes
def test_rejects_non_object(validate, bad):
    """A body that is not a JSON object is rejected before a single field is read."""
    with pytest.raises(ValueError):
        validate(bad)


# age stands for the four numeric fields (they share one `_num` branch); gender and goal have their own.
@pytest.mark.parametrize("field", ["age", "gender", "goal"])
def test_rejects_injection_object_in_any_field(validate, field):
    """A Mongo operator object is refused in EVERY field, so no single one is left as a hole through which a query document reaches the store."""
    p = _ok()
    p[field] = {"$gt": ""}
    with pytest.raises(ValueError):
        validate(p)


def test_rejects_bool_as_age(validate):
    """A bool is an int subclass in Python, so True would pass a naive numeric check — age must be a real number, not a flag."""
    p = _ok()
    p["age"] = True  # bool is an int subclass — must still be rejected
    with pytest.raises(ValueError):
        validate(p)


def test_rejects_bool_as_training_frequency(validate):
    """True equals 1, which is INSIDE the allowed training-frequency range — so unlike age, the range check cannot catch it and the explicit bool gate is the only defence."""
    p = _ok()
    p["training_frequency"] = True
    with pytest.raises(ValueError):
        validate(p)


def test_rejects_string_age(validate):
    """A numeric string is not a number: accepting it would store a string where every later calculation expects an int."""
    p = _ok()
    p["age"] = "30"
    with pytest.raises(ValueError):
        validate(p)


@pytest.mark.parametrize("goal", ["LOSE", {"$ne": None}])   # wrong case + the non-string branch
def test_rejects_unknown_or_non_string_goal(validate, goal):
    """The goal must be one of the documented values, matched exactly — an unknown word, the wrong case, or an operator object is refused rather than stored and silently ignored downstream."""
    p = _ok()
    p["goal"] = goal
    with pytest.raises(ValueError):
        validate(p)


@pytest.mark.parametrize("age", [9, 121])
def test_rejects_out_of_range_age(validate, age):
    """An age outside the plausible range is refused, so a typo cannot drive a calorie calculation that is presented to the user as advice."""
    p = _ok()
    p["age"] = age
    with pytest.raises(ValueError):
        validate(p)


@pytest.mark.parametrize("tf", [-1, 15])
def test_rejects_out_of_range_training_frequency(validate, tf):
    """A negative or impossible number of weekly sessions is refused rather than being fed to the recommendation logic."""
    p = _ok()
    p["training_frequency"] = tf
    with pytest.raises(ValueError):
        validate(p)


@pytest.mark.parametrize("field,lo,hi", [("age", 10, 120), ("training_frequency", 0, 14)])
def test_accepts_int_field_at_its_boundaries(validate, field, lo, hi):
    """The exact minimum and maximum are ACCEPTED, pinning the bounds inclusive — a `<` written where `<=` was meant would reject the lowest legitimate value."""
    for value in (lo, hi):
        assert validate({**_ok(), field: value})[field] == value


@pytest.mark.parametrize("field,lo,hi", [("height", 50, 300), ("weight", 20, 500)])
def test_accepts_number_field_at_its_boundaries(validate, field, lo, hi):
    """The same inclusive-bounds guarantee for the two measured fields, so someone at the extreme of the range can still save a profile."""
    for value in (lo, hi):
        assert validate({**_ok(), field: value})[field] == value


# --------------------------------------------------------------- F5 training preferences (#276)
# `equipment` and `split_preference` are the two inputs F5 needs that the profile never collected.
# Both are OPTIONAL: the contract that matters most is that a payload without them still stores
# exactly the six fields it always did, so profiles saved before this shipped are untouched.


def test_a_payload_without_the_preferences_stores_exactly_the_original_six_fields(validate):
    """The backwards-compatibility contract. If either key leaked in with a default, every profile
    written before this feature would silently change shape."""
    assert set(validate(_ok())) == {"age", "gender", "height", "weight", "goal", "training_frequency"}


def test_gender_is_stored_stripped_of_surrounding_whitespace(validate):
    """Gender is normalised before it is stored, so a value typed with stray spaces is the same value as one typed without.

    It reaches the AI features and any grouping as a plain string, where `" male "` and `"male"` would
    be two different categories. Nothing pinned this: removing the `.strip()` left the whole suite green
    (measured), because every other case supplies an already-clean value.
    """
    assert validate({**_ok(), "gender": "  male  "})["gender"] == "male"


def test_accepts_equipment_and_split_preference(validate):
    """The two optional training preferences are stored when supplied, since a recommendation cannot honour equipment the profile never recorded."""
    out = validate({**_ok(), "equipment": ["barbell", "bands"], "split_preference": "upper_lower"})
    assert out["equipment"] == ["barbell", "bands"]
    assert out["split_preference"] == "upper_lower"


def test_an_explicit_empty_equipment_list_is_kept_not_dropped(validate):
    """"I own no equipment" is an answer, and must not be confused with "never asked"."""
    out = validate({**_ok(), "equipment": []})
    assert "equipment" in out and out["equipment"] == []


def test_equipment_is_deduplicated_in_the_caller_s_order(validate):
    """A repeated selection is collapsed once while keeping the order the user chose, so a double-tap does not weight one item twice."""
    out = validate({**_ok(), "equipment": ["bands", "barbell", "bands"]})
    assert out["equipment"] == ["bands", "barbell"]


@pytest.mark.parametrize("bad", ["barbell", 5])
def test_rejects_equipment_that_is_not_a_list(validate, bad):
    """Equipment must arrive as a list, and is refused AS a list problem — not as a mystery item error.

    The message is what makes this load-bearing. A bare string is the dangerous case (iterating it yields
    individual characters, each treated as equipment) but it raises either way: without the list gate its
    characters simply fail the item check instead, so asserting "some ValueError" proves nothing about the
    gate. Measured: deleting the gate left an earlier version of this test green. `5` is the other half —
    it is not iterable at all, so without the gate it raises TypeError rather than a clean 400.
    """
    with pytest.raises(ValueError, match="must be a list"):
        validate({**_ok(), "equipment": bad})


# ["barbell", "sauna"] is NOT a duplicate: it proves every item is checked, not just the first.
@pytest.mark.parametrize("bad", [["treadmill"], ["barbell", "sauna"], [{"$gt": ""}]])
def test_rejects_an_equipment_item_that_is_not_a_known_value(validate, bad):
    """Every item must be one of the known values — an invented one, an empty string, a null, or a nested structure is refused rather than stored as something no recommendation can interpret."""
    with pytest.raises(ValueError):
        validate({**_ok(), "equipment": bad})


def test_rejects_more_equipment_items_than_exist(validate):
    """A list longer than the number of distinct items that exist is refused, so a caller cannot pad the field with repeats to inflate the stored document."""
    with pytest.raises(ValueError):
        validate({**_ok(), "equipment": ["bodyweight"] * 20})


@pytest.mark.parametrize("bad", ["FULL_BODY", {"$gt": ""}])   # wrong case + the non-string branch
def test_rejects_an_unknown_or_non_string_split_preference(validate, bad):
    """The split preference must be one of the documented values, matched exactly — wrong case, a list, or an operator object is refused."""
    with pytest.raises(ValueError):
        validate({**_ok(), "split_preference": bad})


@pytest.mark.parametrize("split", ["full_body", "upper_lower", "push_pull_legs", "no_preference"])
def test_accepts_every_documented_split(validate, split):
    """Each documented split value is genuinely accepted, so the options offered in the UI all actually save."""
    assert validate({**_ok(), "split_preference": split})["split_preference"] == split


@pytest.mark.parametrize("item", ["bodyweight", "dumbbell", "barbell", "kettlebell", "machine", "bands", "pullup_bar"])
def test_accepts_every_documented_equipment_item(validate, item):
    """Each documented equipment value is genuinely accepted, so nothing the UI offers is rejected on submit."""
    assert validate({**_ok(), "equipment": [item]})["equipment"] == [item]


def test_an_explicit_null_is_treated_as_not_supplied(validate):
    """A client that sends the keys as null (e.g. a cleared form) must not 400 — that would make the
    fields effectively required, which is the opposite of the intent."""
    out = validate({**_ok(), "equipment": None, "split_preference": None})
    assert "equipment" not in out and "split_preference" not in out


# ---------------------------------------------------------------------------
# training_program — PROPOSAL-v2 §3's Advanced-tier input (#566): weekly sets
# per muscle group, the first real input the balance analysis has ever had.
# ---------------------------------------------------------------------------

def test_accepts_a_training_program(validate):
    """The Advanced tier's whole point is providing your own programme, so a well-formed one survives intact."""
    out = validate({**_ok(), "training_program": {"chest": 12, "back": 14}})
    assert out["training_program"] == {"chest": 12, "back": 14}


def test_training_program_is_omitted_when_not_supplied(validate):
    """A profile saved without one must keep exactly its old shape — no key invented for existing users."""
    assert "training_program" not in validate(_ok())


def test_an_explicit_null_training_program_is_treated_as_not_supplied(validate):
    """A cleared form sends null; that must not 400, or the optional field becomes required in practice."""
    assert "training_program" not in validate({**_ok(), "training_program": None})


def test_a_zero_set_group_is_dropped_not_stored(validate):
    """Not training a group and training it for zero sets are the same statement; storing the zero
    would make the balance analysis read calves as trained-but-empty and flag a phantom imbalance."""
    out = validate({**_ok(), "training_program": {"chest": 10, "calves": 0}})
    assert out["training_program"] == {"chest": 10}


@pytest.mark.parametrize("bad", [[], "chest", 5, [("chest", 3)]])
def test_rejects_a_training_program_that_is_not_an_object(validate, bad):
    """A list or a bare string is not a mapping; rejecting it here keeps a malformed shape out of the store."""
    with pytest.raises(ValueError):
        validate({**_ok(), "training_program": bad})


@pytest.mark.parametrize("group", ["forearms", "lats", "", "CHEST"])
def test_rejects_an_unknown_muscle_group(validate, group):
    """Only ai/'s own 10 groups accumulate volume — an unrecognised key would be silently ignored
    downstream, so the athlete's entry would vanish with no error. Reject it where it can be reported."""
    with pytest.raises(ValueError):
        validate({**_ok(), "training_program": {group: 8}})


@pytest.mark.parametrize("sets", [True, False, 8.5, "8", None, [8]])
def test_rejects_non_integer_set_counts(validate, sets):
    """Sets are whole repetitions of work. bool is an int subclass in Python, so True must be rejected
    explicitly or it would store as 1 set."""
    with pytest.raises(ValueError):
        validate({**_ok(), "training_program": {"chest": sets}})


@pytest.mark.parametrize("sets", [-1, 61, 10_000])
def test_rejects_out_of_range_set_counts(validate, sets):
    """A negative week is impossible and an absurd one is a typo; both would skew the balance analysis."""
    with pytest.raises(ValueError):
        validate({**_ok(), "training_program": {"chest": sets}})


def test_rejects_more_groups_than_exist(validate):
    """A payload larger than the taxonomy is malformed by construction — bound it before iterating."""
    program = {f"group{i}": 5 for i in range(20)}
    with pytest.raises(ValueError):
        validate({**_ok(), "training_program": program})


@pytest.mark.parametrize("group", ["chest", "back", "shoulders", "biceps", "triceps",
                                   "quads", "hamstrings", "glutes", "calves", "core"])
def test_accepts_every_muscle_group_the_form_offers(validate, group):
    """Each of the 10 boxes in the profile form must actually be accepted on submit, or the UI lies."""
    assert validate({**_ok(), "training_program": {group: 6}})["training_program"] == {group: 6}
