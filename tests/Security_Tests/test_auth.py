"""MANDATORY auth/security tests — OWNER: Shiri (F1). Required by the rubric (docs/FEEDBACK.md) + DESIGN §5.

TDD: write these before/with the implementation. Remove the module `skip` + fill each body as you go.
Never comment out a broken test — fix it or delete it (course rule).
"""
import pytest

pytestmark = pytest.mark.skip(reason="TDD scaffold — Shiri fills these with F1 auth (remove skip as you go)")


def test_password_is_hashed_not_plaintext():
    """A stored password must be a werkzeug hash, never the plaintext."""
    raise NotImplementedError


def test_wrong_password_returns_401():
    """Login with the wrong password -> 401."""
    raise NotImplementedError


def test_protected_endpoint_without_login_returns_401():
    """A gated endpoint (e.g. /profile) without a session -> 401."""
    raise NotImplementedError


def test_nosql_injection_payload_rejected():
    """A login payload like {"username": {"$gt": ""}} must be rejected, not run as a query."""
    raise NotImplementedError
