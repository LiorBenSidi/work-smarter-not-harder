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
    out = validate(_ok())
    assert out["age"] == 30
    assert out["goal"] == "maintain"
    assert out["training_frequency"] == 3


def test_accepts_float_height_and_weight(validate):
    p = _ok()
    p["height"], p["weight"] = 175.5, 72.4
    out = validate(p)
    assert out["height"] == 175.5
    assert out["weight"] == 72.4


@pytest.mark.parametrize("bad", [None, [], "x", 5])
def test_rejects_non_object(validate, bad):
    with pytest.raises(ValueError):
        validate(bad)


@pytest.mark.parametrize("field", ["age", "gender", "height", "weight", "goal", "training_frequency"])
def test_rejects_injection_object_in_any_field(validate, field):
    p = _ok()
    p[field] = {"$gt": ""}
    with pytest.raises(ValueError):
        validate(p)


def test_rejects_bool_as_age(validate):
    p = _ok()
    p["age"] = True  # bool is an int subclass — must still be rejected
    with pytest.raises(ValueError):
        validate(p)


def test_rejects_bool_as_training_frequency(validate):
    # True == 1 is IN the training_frequency range [0,14], so the bool gate is the only defense here
    p = _ok()
    p["training_frequency"] = True
    with pytest.raises(ValueError):
        validate(p)


def test_rejects_string_age(validate):
    p = _ok()
    p["age"] = "30"
    with pytest.raises(ValueError):
        validate(p)


@pytest.mark.parametrize("goal", ["bulk", "", "LOSE", {"$ne": None}])
def test_rejects_unknown_or_non_string_goal(validate, goal):
    p = _ok()
    p["goal"] = goal
    with pytest.raises(ValueError):
        validate(p)


@pytest.mark.parametrize("age", [9, 121])
def test_rejects_out_of_range_age(validate, age):
    p = _ok()
    p["age"] = age
    with pytest.raises(ValueError):
        validate(p)


@pytest.mark.parametrize("tf", [-1, 15])
def test_rejects_out_of_range_training_frequency(validate, tf):
    p = _ok()
    p["training_frequency"] = tf
    with pytest.raises(ValueError):
        validate(p)


@pytest.mark.parametrize("field,lo,hi", [("age", 10, 120), ("training_frequency", 0, 14)])
def test_accepts_int_field_at_its_boundaries(validate, field, lo, hi):
    # the exact min/max are ACCEPTED (pins the <= bounds — a `<` off-by-one would reject lo)
    for value in (lo, hi):
        assert validate({**_ok(), field: value})[field] == value


@pytest.mark.parametrize("field,lo,hi", [("height", 50, 300), ("weight", 20, 500)])
def test_accepts_number_field_at_its_boundaries(validate, field, lo, hi):
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


def test_accepts_equipment_and_split_preference(validate):
    out = validate({**_ok(), "equipment": ["barbell", "bands"], "split_preference": "upper_lower"})
    assert out["equipment"] == ["barbell", "bands"]
    assert out["split_preference"] == "upper_lower"


def test_an_explicit_empty_equipment_list_is_kept_not_dropped(validate):
    """"I own no equipment" is an answer, and must not be confused with "never asked"."""
    out = validate({**_ok(), "equipment": []})
    assert "equipment" in out and out["equipment"] == []


def test_equipment_is_deduplicated_in_the_caller_s_order(validate):
    out = validate({**_ok(), "equipment": ["bands", "barbell", "bands"]})
    assert out["equipment"] == ["bands", "barbell"]


@pytest.mark.parametrize("bad", [{"$gt": ""}, "barbell", 5, 3.5, True, {"0": "barbell"}])
def test_rejects_equipment_that_is_not_a_list(validate, bad):
    # a bare string is the dangerous one: iterating it would yield characters, not equipment
    with pytest.raises(ValueError):
        validate({**_ok(), "equipment": bad})


@pytest.mark.parametrize("bad", [["treadmill"], ["barbell", "sauna"], [""], [None], [True], [{"$gt": ""}], [["barbell"]]])
def test_rejects_an_equipment_item_that_is_not_a_known_value(validate, bad):
    with pytest.raises(ValueError):
        validate({**_ok(), "equipment": bad})


def test_rejects_more_equipment_items_than_exist(validate):
    with pytest.raises(ValueError):
        validate({**_ok(), "equipment": ["bodyweight"] * 20})


@pytest.mark.parametrize("bad", [{"$gt": ""}, "", "bro_split", 5, True, ["full_body"], "FULL_BODY"])
def test_rejects_an_unknown_or_non_string_split_preference(validate, bad):
    with pytest.raises(ValueError):
        validate({**_ok(), "split_preference": bad})


@pytest.mark.parametrize("split", ["full_body", "upper_lower", "push_pull_legs", "no_preference"])
def test_accepts_every_documented_split(validate, split):
    assert validate({**_ok(), "split_preference": split})["split_preference"] == split


@pytest.mark.parametrize("item", ["bodyweight", "dumbbell", "barbell", "kettlebell", "machine", "bands", "pullup_bar"])
def test_accepts_every_documented_equipment_item(validate, item):
    assert validate({**_ok(), "equipment": [item]})["equipment"] == [item]


def test_an_explicit_null_is_treated_as_not_supplied(validate):
    """A client that sends the keys as null (e.g. a cleared form) must not 400 — that would make the
    fields effectively required, which is the opposite of the intent."""
    out = validate({**_ok(), "equipment": None, "split_preference": None})
    assert "equipment" not in out and "split_preference" not in out
