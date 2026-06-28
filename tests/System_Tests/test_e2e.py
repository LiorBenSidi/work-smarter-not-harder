"""MANDATORY system (end-to-end) test. OWNER: Lior (the web->ai->db system flow) + Shiri (ai).
Elad runs it against the live stack via the containerized test-runner.

TDD: fill + un-skip when auth + profile + dashboard exist.
"""
import pytest

pytestmark = pytest.mark.skip(reason="TDD scaffold — fill when the register->profile->readiness flow exists")


def test_register_login_profile_then_readiness_on_dashboard():
    """Happy path: register -> login -> save profile -> see a readiness state on the dashboard."""
    raise NotImplementedError
