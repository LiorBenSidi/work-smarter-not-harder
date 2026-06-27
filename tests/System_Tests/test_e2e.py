"""MANDATORY system (end-to-end) test. OWNER: Shiri + Elad.

TDD: fill + un-skip when auth + profile + dashboard exist.
"""
import pytest

pytestmark = pytest.mark.skip(reason="TDD scaffold — fill when the register->profile->readiness flow exists")


def test_register_login_profile_then_readiness_on_dashboard():
    """Happy path: register -> login -> save profile -> see a readiness state on the dashboard."""
    raise NotImplementedError
