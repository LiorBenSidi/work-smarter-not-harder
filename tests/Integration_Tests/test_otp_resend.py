"""Integration tests for the OTP challenge's expiry + resend (a fresh login code). OWNER: Lior.

`otp_client` runs with 2-step OTP active and no SMTP, so the code is surfaced in the response — which
is how these read it. The UI counts down from `expires_in` and offers Resend after 30s.
"""


def _register(c, username="alice", password="s3cretpw!"):
    c.post("/register", json={"username": username, "password": password, "email": f"{username}@ex.com"})


def _start_login(c, username="alice", password="s3cretpw!"):
    """Register + login to reach the OTP step; returns the /login JSON (dev_otp + expires_in)."""
    _register(c, username, password)
    return c.post("/login", json={"username": username, "password": password}).get_json()


def test_login_challenge_exposes_expires_in(otp_client):
    """The challenge tells the client how long the code lasts, so the countdown a user watches reflects the server's real deadline rather than a number the interface invented."""
    data = _start_login(otp_client)
    assert data["status"] == "otp_required"
    assert data["expires_in"] == 600        # OTP_TTL_SECONDS — the UI counts down to code-expiry from this
    assert data["dev_otp"]                   # dev/no-SMTP surfaces the code


def test_resend_issues_a_fresh_code_and_verifies(otp_client):
    """A resent code genuinely completes the sign-in, so someone whose first email was slow or lost is not locked out of their own account."""
    _start_login(otp_client)
    resent = otp_client.post("/resend-otp").get_json()
    assert resent["status"] == "otp_sent"
    assert resent["expires_in"] == 600
    assert resent["dev_otp"]
    # the freshly-issued code completes the login (the app keeps one live challenge at a time)
    assert otp_client.post("/verify-otp", json={"code": resent["dev_otp"]}).status_code == 200


def test_resend_supersedes_the_previous_code(otp_client, monkeypatch):
    """Resending issues a NEW code and retires the old one, so a code sitting in an inbox stops working the moment a fresh one is requested.

    The generator is pinned to guarantee the two differ: the earlier version guarded the comparison with an `if`, which meant a regression making resend reuse the same code — the exact thing this catches — skipped the assertion and passed.
    The new code is then verified too, so the refusal above is proven to be about staleness rather than a broken challenge.
    """
    import itertools
    from web.routes import auth as auth_module
    counter = itertools.count(1)
    monkeypatch.setattr(auth_module.secrets, "randbelow", lambda _n: next(counter))

    first = _start_login(otp_client)
    resent = otp_client.post("/resend-otp").get_json()
    assert first["dev_otp"] != resent["dev_otp"], "resend must issue a NEW code, not reuse the old one"
    # re-issuing replaces the stored hash, so the OLD code no longer verifies
    assert otp_client.post("/verify-otp", json={"code": first["dev_otp"]}).status_code == 401
    # ...and the current one still does, so the refusal above is about staleness, not a broken challenge
    assert otp_client.post("/verify-otp", json={"code": resent["dev_otp"]}).status_code == 200


def test_resend_without_a_pending_login_is_400(otp_client):
    """There is nothing to resend when no sign-in is in progress, so the endpoint cannot be used on its own to have codes mailed to someone."""
    assert otp_client.post("/resend-otp").status_code == 400
