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
    """A well-formed check-in passes with its values intact, so the gate does not turn away genuine entries."""
    out = validate(_ok())
    assert out["sleep_hours"] == 7.5
    assert out["resting_hr"] == 55
    assert out["training_load"] == 6


@pytest.mark.parametrize("bad", [None, [], "x", 5])
def test_rejects_non_object(validate, bad):
    """A body that is not a JSON object is rejected before a single field is read."""
    with pytest.raises(ValueError):
        validate(bad)


@pytest.mark.parametrize("field", ["sleep_hours", "resting_hr", "fatigue", "soreness", "training_load"])
def test_rejects_missing_field(validate, field):
    """All five metrics are required — a check-in missing any of them cannot be scored, so it is refused rather than stored half-empty."""
    p = _ok()
    del p[field]
    with pytest.raises(ValueError):
        validate(p)


@pytest.mark.parametrize("field", ["sleep_hours", "resting_hr", "fatigue", "soreness", "training_load"])
def test_rejects_injection_object_in_any_field(validate, field):
    """A Mongo operator object is refused in EVERY field, not merely the first one checked, so no single metric is left as a hole in the wall."""
    p = _ok()
    p[field] = {"$gt": ""}
    with pytest.raises(ValueError):
        validate(p)


def test_rejects_bool_as_number(validate):
    """A bool is an int subclass in Python, so True would sail through a naive numeric check — it has to be rejected as not a real measurement."""
    p = _ok()
    p["fatigue"] = True  # bool is an int subclass — must still be rejected
    with pytest.raises(ValueError):
        validate(p)


def test_rejects_string_number(validate):
    """A numeric string is not a number: accepting it would put a string into the stored history and into the model's input."""
    p = _ok()
    p["resting_hr"] = "55"
    with pytest.raises(ValueError):
        validate(p)


def test_rejects_float_for_an_integer_field(validate):
    """A field measured in whole units rejects a fractional value instead of silently truncating it."""
    p = _ok()
    p["resting_hr"] = 55.5  # resting_hr is an integer field
    with pytest.raises(ValueError):
        validate(p)


@pytest.mark.parametrize("field,bad", [("resting_hr", 500), ("sleep_hours", -1), ("fatigue", 11), ("training_load", -1)])
def test_rejects_out_of_range(validate, field, bad):
    """Values outside the physically meaningful range are refused, so a typo cannot become a stored measurement that the model then scores as real."""
    p = _ok()
    p[field] = bad
    with pytest.raises(ValueError):
        validate(p)


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_rejects_non_finite_numbers(validate, bad):
    """Python's JSON parser accepts Infinity and NaN as a non-standard extension, so a hand-crafted body can smuggle them past a type check.

    An explicit finiteness guard rejects them before any range comparison or AI call — a naive lo <= NaN <= hi is False by accident rather than by intent.
    """
    with pytest.raises(ValueError):
        validate({**_ok(), "sleep_hours": bad})


@pytest.mark.parametrize("bad", [0, 0.5])
def test_rejects_sub_one_sleep_to_match_the_model_contract(validate, bad):
    """The producer's accepted range must not exceed what the model accepts.

    Check-in once allowed sleep_hours >= 0 while the readiness model requires >= 1, so a "0 hours" entry validated, was stored, and then made every prediction on it fail — showing a sticky, false "AI service down" until the user happened to submit another check-in.
    """
    with pytest.raises(ValueError):
        validate({**_ok(), "sleep_hours": bad})


@pytest.mark.parametrize("field,lo,hi", [("sleep_hours", 1, 24), ("fatigue", 1, 10), ("training_load", 0, 10), ("resting_hr", 30, 220)])
def test_accepts_the_exact_boundaries(validate, field, lo, hi):
    """The exact low and high bound of every range is accepted, pinning them inclusive so a tightened comparison cannot quietly start rejecting legitimate extremes."""
    for value in (lo, hi):
        assert validate({**_ok(), field: value})[field] == value
