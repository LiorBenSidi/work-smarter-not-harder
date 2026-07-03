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
    data = _start_login(otp_client)
    assert data["status"] == "otp_required"
    assert data["expires_in"] == 600        # OTP_TTL_SECONDS — the UI counts down to code-expiry from this
    assert data["dev_otp"]                   # dev/no-SMTP surfaces the code


def test_resend_issues_a_fresh_code_and_verifies(otp_client):
    _start_login(otp_client)
    resent = otp_client.post("/resend-otp").get_json()
    assert resent["status"] == "otp_sent"
    assert resent["expires_in"] == 600
    assert resent["dev_otp"]
    # the freshly-issued code completes the login (the app keeps one live challenge at a time)
    assert otp_client.post("/verify-otp", json={"code": resent["dev_otp"]}).status_code == 200


def test_resend_supersedes_the_previous_code(otp_client):
    first = _start_login(otp_client)
    resent = otp_client.post("/resend-otp").get_json()
    if first["dev_otp"] != resent["dev_otp"]:            # (guard the ~1e-6 chance of an identical code)
        # re-issuing replaces the stored hash, so the OLD code no longer verifies
        assert otp_client.post("/verify-otp", json={"code": first["dev_otp"]}).status_code == 401


def test_resend_without_a_pending_login_is_400(otp_client):
    # nothing to resend if no /login started a challenge on this session
    assert otp_client.post("/resend-otp").status_code == 400
