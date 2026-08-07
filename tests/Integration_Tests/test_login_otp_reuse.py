"""Login-OTP reuse on rapid repeat logins. OWNER: Lior (F1).

Root cause validated live on 16 Jul: every /login minted a NEW code and OVERWROTE the previous one, so a
burst of logins left only the last code valid — and the burst of emails tripped the mail provider's
free-tier rate limit (codes arrived batched, minutes late, mostly already dead). The fix: in live-SMTP
mode, reuse a still-valid code instead of minting a new one, so N rapid logins => ONE code + ONE email.

These run with OTP ACTIVE (make_otp_client). Live-SMTP behaviour is exercised by setting SMTP_HOST and
capturing send_email (the code otherwise only leaves by real email); the dev/no-SMTP path is regression-
guarded so the no-SMTP sign-in flow — which reads the surfaced code — keeps working.
"""
import re
import time

import pytest

PW = "s3cretpw!"


def _register(client, username="alice"):
    return client.post("/register", json={"username": username, "password": PW,
                                          "email": f"{username}@example.com"})


def _login(client, username="alice"):
    return client.post("/login", json={"username": username, "password": PW})


def _code(mail):
    """Pull the 6-digit code out of a captured email body."""
    return re.search(r"\b(\d{6})\b", mail["body"]).group(1)


@pytest.fixture
def live_otp(make_otp_client, fake_users, auth_module, monkeypatch):
    """OTP-active client in LIVE-SMTP mode with send_email captured (each call appends to `sent`)."""
    sent = []
    monkeypatch.setattr(auth_module, "send_email",
                        lambda cfg, to, subject, body, **kw: sent.append(
                            {"to": to, "subject": subject, "body": body}) or True)
    client = make_otp_client(fake_users, SMTP_HOST="smtp.example.com")
    return client, fake_users, sent


def test_rapid_relogin_reuses_code_and_sends_one_email(live_otp):
    """A burst of sign-in attempts sends ONE email and keeps one code alive.

    Minting a fresh code each time invalidated the previous one and flooded the mail provider, so codes arrived late, batched, and mostly already dead. The remaining time is reported as what is actually left, not a reset full window.
    """
    client, _users, sent = live_otp
    _register(client)
    b1 = _login(client).get_json()
    b2 = _login(client).get_json()
    assert b1["status"] == "otp_required" and b1["code_sent"] is True     # first login: fresh code emailed
    assert b2["status"] == "otp_required" and b2["code_sent"] is False    # rapid repeat: reused, no new email
    assert len(sent) == 1                                                 # ONE email for the whole burst
    assert 0 < b2["expires_in"] < 600                                     # remaining time, NOT a reset full TTL


def test_reused_code_still_verifies(live_otp):
    """The single code from the burst genuinely works, so collapsing the emails does not cost the user their way in."""
    client, _users, sent = live_otp
    _register(client)
    for _ in range(3):                                                    # 3 rapid logins
        _login(client)
    assert len(sent) == 1                                                 # only the first emailed a code
    code = _code(sent[0])
    assert client.post("/verify-otp", json={"code": code}).get_json()["status"] == "logged in"


def test_expired_code_is_reminted(live_otp):
    """Once the code has expired a fresh one is minted and sent — reuse must never mean a user is handed something already dead."""
    client, users, sent = live_otp
    _register(client)
    _login(client)
    assert len(sent) == 1
    challenge = users.get_otp("alice")
    users.set_otp("alice", challenge["otp_hash"], time.time() - 1)        # same code, but now past its expiry
    b2 = _login(client).get_json()
    assert b2["code_sent"] is True and len(sent) == 2                     # expired -> a fresh code is minted + sent


def test_reuse_preserves_attempt_counter(live_otp):
    """Reusing the code keeps the failed-attempt count, so signing in again cannot be used to reset the counter and dodge the lockout."""
    client, users, sent = live_otp
    _register(client)
    _login(client)
    real = _code(sent[0])
    wrong = "111111" if real != "111111" else "222222"
    client.post("/verify-otp", json={"code": wrong})                     # one wrong guess -> attempts = 1
    assert users.get_otp("alice")["attempts"] == 1
    b2 = _login(client).get_json()
    assert b2["code_sent"] is False                                      # reused (didn't re-mint)
    assert users.get_otp("alice")["attempts"] == 1                       # NOT reset to 0 -> re-login can't dodge lockout


def test_dev_mode_mints_fresh_each_login(otp_client):
    """Reuse applies only when mail is really being sent; without a relay each sign-in mints fresh, so the development flow that reads the code from the response keeps working."""
    _register(otp_client)
    b1 = _login(otp_client).get_json()
    b2 = _login(otp_client).get_json()
    assert b1["code_sent"] is True and b2["code_sent"] is True
    assert "dev_otp" in b1 and "dev_otp" in b2                            # both minted fresh (dev never reuses)


def test_failed_send_clears_challenge_so_next_login_reattempts(make_otp_client, fake_users, auth_module, monkeypatch):
    """If the send fails, the stored challenge is discarded so the next attempt mints and sends again.

    Otherwise reuse would lock onto a code the user never received and every retry would helpfully reuse it.
    """
    calls = {"n": 0}

    def failing_send(cfg, to, subject, body, **kw):
        calls["n"] += 1
        return False                                                     # simulate a configured SMTP send failing

    monkeypatch.setattr(auth_module, "send_email", failing_send)
    client = make_otp_client(fake_users, SMTP_HOST="smtp.example.com")
    _register(client)
    assert _login(client).get_json()["status"] == "otp_required"
    assert fake_users.get_otp("alice") is None                           # failed send -> no lingering dead challenge
    b2 = _login(client).get_json()
    assert b2["code_sent"] is True and calls["n"] == 2                   # next login re-attempts the send (self-heal)


def test_locked_challenge_is_reminted_not_reused(live_otp):
    """A challenge that has already hit the attempt cap is replaced rather than reused, so a locked-out user is not handed back the same dead code forever."""
    client, users, sent = live_otp
    _register(client)
    _login(client)                                                       # code A, one email
    for _ in range(5):                                                   # drive attempts to the lockout cap...
        users.bump_otp_attempts("alice")                                 # ...WITHOUT clearing the slot
    assert users.get_otp("alice")["attempts"] == 5
    b2 = _login(client).get_json()
    assert b2["code_sent"] is True and len(sent) == 2                    # locked slot -> re-mint + fresh email, not reuse


def test_resend_still_mints_fresh_even_with_a_valid_code(live_otp):
    """An explicit resend always issues a new code, because the user asking for one is saying the previous one did not reach them — reuse would answer that request with silence."""
    client, _users, sent = live_otp
    _register(client)
    _login(client)                                                       # code A emailed
    r = client.post("/resend-otp")                                       # explicit resend -> FRESH code B
    assert r.status_code == 200 and len(sent) == 2                       # a new email went out despite A being valid
    code_b = _code(sent[1])
    assert client.post("/verify-otp", json={"code": code_b}).get_json()["status"] == "logged in"
