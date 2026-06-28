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
