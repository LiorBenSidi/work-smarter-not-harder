"""MANDATORY stress test — OWNER: Elad (locust).

Stress tests need a running stack, so they are NOT a per-commit merge gate — run them on demand
(a separate CI job / locally) per the course's stress-testing lab. TDD: fill + un-skip when the stack runs.
"""
import pytest

pytestmark = pytest.mark.skip(reason="TDD scaffold — Elad adds a locust scenario; runs on demand, not per-commit")


def test_predict_and_auth_under_concurrent_load():
    """The stack handles a burst of concurrent /predict + auth requests without crashing (429, not 500)."""
    raise NotImplementedError
