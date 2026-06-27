"""MANDATORY integration test — web -> ai. OWNER: Lior (web) + Shiri (ai).

TDD: fill + un-skip when the web routes and ai `/predict` are implemented.
"""
import pytest

pytestmark = pytest.mark.skip(reason="TDD scaffold — fill when web routes + ai /predict exist")


def test_dashboard_triggers_ai_predict_roundtrip():
    """A logged-in dashboard request makes a web->ai /predict call and renders the returned state."""
    raise NotImplementedError
