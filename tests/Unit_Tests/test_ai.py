"""MANDATORY unit tests for the AI — OWNER: Shiri (F3 readiness + recommendations).

TDD: write these before/with the model. Remove the module `skip` + fill each body as you implement.
Never comment out a broken test — fix it or delete it (course rule).
"""
import pytest

pytestmark = pytest.mark.skip(reason="TDD scaffold — Shiri fills these with the model (remove skip as you go)")


def test_predict_returns_a_valid_class():
    """/predict maps a known feature vector to one of the defined training-state classes."""
    raise NotImplementedError


def test_binning_maps_boundary_values():
    """The readiness->class binning maps boundary values (0, 4, 5, 7, 8, 10) to the right class."""
    raise NotImplementedError
