"""Unit tests for the daily check-in validation. OWNER: Lior.

A check-in is valid only when it's a JSON object with the right field TYPES and ranges. Bools,
non-numbers, injection objects, and out-of-range values are rejected by `validate_checkin` before
anything is forwarded to the AI or written to history.
"""
import sys

import pytest


@pytest.fixture
def validate(web_app_module):
    return sys.modules["routes.checkin"].validate_checkin


def _ok():
    return {"sleep_hours": 7.5, "resting_hr": 55, "fatigue": 3, "soreness": 2, "training_load": 6}


def test_accepts_a_valid_checkin(validate):
    out = validate(_ok())
    assert out["sleep_hours"] == 7.5
    assert out["resting_hr"] == 55
    assert out["training_load"] == 6


@pytest.mark.parametrize("bad", [None, [], "x", 5])
def test_rejects_non_object(validate, bad):
    with pytest.raises(ValueError):
        validate(bad)


@pytest.mark.parametrize("field", ["sleep_hours", "resting_hr", "fatigue", "soreness", "training_load"])
def test_rejects_missing_field(validate, field):
    p = _ok()
    del p[field]
    with pytest.raises(ValueError):
        validate(p)


@pytest.mark.parametrize("field", ["sleep_hours", "resting_hr", "fatigue", "soreness", "training_load"])
def test_rejects_injection_object_in_any_field(validate, field):
    p = _ok()
    p[field] = {"$gt": ""}
    with pytest.raises(ValueError):
        validate(p)


def test_rejects_bool_as_number(validate):
    p = _ok()
    p["fatigue"] = True  # bool is an int subclass — must still be rejected
    with pytest.raises(ValueError):
        validate(p)


def test_rejects_string_number(validate):
    p = _ok()
    p["resting_hr"] = "55"
    with pytest.raises(ValueError):
        validate(p)


def test_rejects_float_for_an_integer_field(validate):
    p = _ok()
    p["resting_hr"] = 55.5  # resting_hr is an integer field
    with pytest.raises(ValueError):
        validate(p)


@pytest.mark.parametrize("field,bad", [("resting_hr", 500), ("sleep_hours", -1), ("fatigue", 11), ("training_load", -1)])
def test_rejects_out_of_range(validate, field, bad):
    p = _ok()
    p[field] = bad
    with pytest.raises(ValueError):
        validate(p)


@pytest.mark.parametrize("bad", [0, 0.5])
def test_rejects_sub_one_sleep_to_match_the_model_contract(validate, bad):
    # Regression: the ai readiness model rejects sleep_hours < 1 (ai/app.py READINESS_FIELDS). The check-in
    # once accepted sleep_hours >= 0, so a "0 hours" entry validated and was stored, then every /predict on
    # it 400'd -> a STICKY false "AI service down" on the dashboard until a new check-in with sleep >= 1.
    # The producer's range must not exceed what the model accepts; sub-1 sleep is refused here.
    with pytest.raises(ValueError):
        validate({**_ok(), "sleep_hours": bad})


@pytest.mark.parametrize("field,lo,hi", [("sleep_hours", 1, 24), ("fatigue", 1, 10), ("training_load", 0, 10), ("resting_hr", 30, 220)])
def test_accepts_the_exact_boundaries(validate, field, lo, hi):
    for value in (lo, hi):
        assert validate({**_ok(), field: value})[field] == value
