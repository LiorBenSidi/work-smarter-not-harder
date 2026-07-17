"""Auth-mode-aware sign-in for the live (``E2E_BASE_URL``) system tests — OWNER: Elad. (#336)

The live E2E tests point a real ``requests.Session`` at a running stack. That stack's auth mode is NOT
fixed: CI's ``compose-e2e`` runs ``TESTING=1`` (email-verify + login-OTP both OFF, so register creates the
account and login is one step), but the documented ``docker compose up`` dev stack — and the prod deploy —
run both ON by default. A test that hard-codes ``register -> login`` only works on the first kind and 401s
on the second (register returns ``verify_required`` and never creates the account).

``sign_in`` drives whichever flow the target stack advertises, so the same test runs green against a
TESTING stack, a normal dev stack, or any mock-email stack. When the stack emails the code for real
(``SMTP_*`` set — the real prod deploy), the code isn't in the HTTP response and the flow can't be
automated, so it ``pytest.skip``s cleanly (matching the suite's existing skip-when-not-applicable style).

Mirrors the 2-step signup that ``tests/Stress_Tests/locustfile_full_system.py`` already performs.
"""
import pytest

TIMEOUT = 15


def csrf_headers(session):
    """The double-submit CSRF header every unsafe request needs (token seeded by a prior GET)."""
    return {"X-CSRF-Token": session.cookies.get("csrf_token", "")}


def sign_in(session, base, user, password, email=None):
    """Register ``user`` and leave ``session`` authenticated, on whatever auth mode ``base`` runs.

    Returns nothing; asserts each step. Skips (never fails) when the stack emails codes for real, since
    the verify/OTP code is then not in the response and sign-in can't be automated.
    """
    email = email or f"{user}@example.com"
    r = session.post(f"{base}/register", json={"username": user, "password": password, "email": email},
                     headers=csrf_headers(session), timeout=TIMEOUT)
    assert r.status_code in (200, 201), r.text
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}

    if body.get("status") == "verify_required":
        # Verify-on stack: the account isn't created until the emailed code is confirmed. Mock-email mode
        # surfaces it as ``dev_code``; a live-email stack doesn't, so we can't automate it -> skip.
        code = body.get("dev_code")
        if code is None:
            pytest.skip("stack emails the registration code (live email) — sign-in can't be automated")
        rv = session.post(f"{base}/register/verify", json={"code": code},
                          headers=csrf_headers(session), timeout=TIMEOUT)
        assert rv.status_code in (200, 201), rv.text
        session.get(f"{base}/health", timeout=TIMEOUT)   # verify rotates the session -> reseed the CSRF token
        return

    # Verify-off stack (TESTING / instant create): log in, completing login-OTP if that's on.
    r = session.post(f"{base}/login", json={"username": user, "password": password},
                     headers=csrf_headers(session), timeout=TIMEOUT)
    assert r.status_code == 200, r.text
    lb = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if lb.get("status") == "otp_required":
        code = lb.get("dev_otp")
        if code is None:
            pytest.skip("stack emails the login code (live email) — sign-in can't be automated")
        rv = session.post(f"{base}/verify-otp", json={"code": code},
                          headers=csrf_headers(session), timeout=TIMEOUT)
        assert rv.status_code == 200, rv.text
        session.get(f"{base}/health", timeout=TIMEOUT)   # OTP verify rotates the session -> reseed CSRF
