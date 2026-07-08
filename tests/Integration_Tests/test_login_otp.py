"""Integration tests for 2-step login verification (email OTP + remember-this-browser). OWNER: Lior (F1).

These run with OTP ACTIVE (the `otp_client` / `make_otp_client` fixtures set OTP_ENABLED on + TESTING off,
SMTP unset so the code is dev-surfaced) — the classic one-step flow is covered by test_auth_flow.py and
its TESTING gate is regression-guarded here too.

Security bar (must EXCEED kerenhovav1/Olympics, which stores the OTP in plaintext + a raw token +
secure:false): the code is stored only as a werkzeug hash, expires, locks out after N wrong guesses, is
bound to the browser session that requested it, and the remember cookie is signed + HttpOnly + tied to
the password hash so a password change revokes it.
"""
import re

PW = "s3cretpw!"


def _register(client, username="alice", password=PW, email=None):
    return client.post("/register", json={"username": username, "password": password,
                                          "email": email or f"{username}@example.com"})


def _login(client, username="alice", password=PW):
    return client.post("/login", json={"username": username, "password": password})


def test_login_returns_otp_required_when_active(otp_client):
    _register(otp_client)
    body = _login(otp_client).get_json()
    assert body["status"] == "otp_required" and body["username"] == "alice"
    assert otp_client.get("/me").status_code == 401           # password alone does NOT grant a session


def test_dev_otp_surfaced_without_smtp_and_verifies(otp_client):
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]           # dev/no-SMTP -> code surfaced for grading
    assert re.fullmatch(r"\d{6}", code)
    v = otp_client.post("/verify-otp", json={"code": code})
    assert v.status_code == 200 and v.get_json()["status"] == "logged in"
    assert otp_client.get("/me").get_json()["username"] == "alice"


def test_otp_not_surfaced_when_smtp_configured(make_otp_client, fake_users, auth_module, monkeypatch):
    sent = {}
    monkeypatch.setattr(auth_module, "send_email",
                        lambda cfg, to, subject, body, **kw: sent.update(to=to, body=body) or True)
    client = make_otp_client(fake_users, SMTP_HOST="smtp.example.com")
    _register(client)
    body = _login(client).get_json()
    assert "dev_otp" not in body                              # SMTP set -> the code is never in the response
    code = re.search(r"\b(\d{6})\b", sent["body"]).group(1)   # ...it only leaves by the (captured) email
    assert client.post("/verify-otp", json={"code": code}).status_code == 200


def test_otp_is_stored_hashed_not_plaintext(otp_client, fake_users):
    # the differentiator vs Olympics: a DB peek reveals only a hash, never the live code.
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]
    stored = fake_users._by_name["alice"]["otp_hash"]
    assert code not in stored and stored.startswith(("pbkdf2:", "scrypt:", "argon2"))


def test_wrong_code_rejected_then_locks_out(otp_client):
    _register(otp_client)
    _login(otp_client)
    for _ in range(4):                                        # OTP_MAX_ATTEMPTS=5: first four are 401
        r = otp_client.post("/verify-otp", json={"code": "000000"})
        assert r.status_code == 401 and r.get_json()["error"] == "incorrect code"
    assert otp_client.post("/verify-otp", json={"code": "000000"}).status_code == 429   # 5th -> lockout
    # challenge + pending session cleared -> must start a fresh login
    assert otp_client.post("/verify-otp", json={"code": "000000"}).status_code == 400


def test_expired_code_is_rejected(otp_client, fake_users):
    _register(otp_client)
    _login(otp_client)
    fake_users._by_name["alice"]["otp_expires_at"] = 0        # force the stored challenge past its TTL
    r = otp_client.post("/verify-otp", json={"code": "000000"})
    assert r.status_code == 400 and "expired" in r.get_json()["error"]


def test_remember_this_browser_skips_otp_next_login(otp_client):
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]
    otp_client.post("/verify-otp", json={"code": code, "remember": True})
    r2 = _login(otp_client).get_json()                        # same, now-trusted browser
    assert r2["status"] == "logged in" and "dev_otp" not in r2


def test_remember_cookie_is_signed_and_httponly(otp_client):
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]
    v = otp_client.post("/verify-otp", json={"code": code, "remember": True})
    set_cookie = v.headers.get("Set-Cookie", "")
    assert "remember_token=" in set_cookie and "HttpOnly" in set_cookie


def test_no_remember_flag_sets_no_cookie_and_still_prompts(otp_client):
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]
    v = otp_client.post("/verify-otp", json={"code": code})   # remember omitted
    assert "remember_token" not in v.headers.get("Set-Cookie", "")
    assert _login(otp_client).get_json()["status"] == "otp_required"


def test_password_change_invalidates_remember_cookie(otp_client, fake_users, auth_module):
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]
    otp_client.post("/verify-otp", json={"code": code, "remember": True})
    fake_users.set_password("alice", auth_module.generate_password_hash("N3wpassword!"))
    # the embedded password-hash tail no longer matches -> the trusted browser must re-verify
    assert otp_client.post("/login", json={"username": "alice", "password": "N3wpassword!"}
                           ).get_json()["status"] == "otp_required"


def test_logout_clears_remember_cookie(otp_client):
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]
    otp_client.post("/verify-otp", json={"code": code, "remember": True})
    otp_client.post("/logout")                                # withdraws trust in this browser
    assert _login(otp_client).get_json()["status"] == "otp_required"


def test_verify_otp_requires_a_pending_login(otp_client):
    _register(otp_client)
    r = otp_client.post("/verify-otp", json={"code": "123456"})   # no /login first
    assert r.status_code == 400


def test_verify_otp_is_bound_to_the_session_user(make_otp_client, fake_users):
    # a code issued to alice can't be redeemed from a browser that never started alice's login.
    _register(make_otp_client(fake_users), "alice")
    victim = make_otp_client(fake_users)
    code = victim.post("/login", json={"username": "alice", "password": PW}).get_json()["dev_otp"]
    attacker = make_otp_client(fake_users)                    # fresh browser, no pending_otp_user
    assert attacker.post("/verify-otp", json={"code": code}).status_code == 400


def test_otp_is_off_under_testing(client):
    # regression guard: the TESTING gate keeps the classic one-step flow for the rest of the suite.
    client.post("/register", json={"username": "alice", "password": PW, "email": "alice@example.com"})
    r = client.post("/login", json={"username": "alice", "password": PW}).get_json()
    assert r["status"] == "logged in" and "dev_otp" not in r


def test_verify_otp_terminal_errors_signal_restart(otp_client):
    # A wrong code is recoverable (401, no restart -> the client stays on the code form); a lockout is
    # TERMINAL (429, restart -> the client routes back to login instead of stranding a dead code form).
    _register(otp_client)
    _login(otp_client)
    wrong = otp_client.post("/verify-otp", json={"code": "000000"})
    assert wrong.status_code == 401 and not wrong.get_json().get("restart")          # recoverable -> stay
    for _ in range(3):
        otp_client.post("/verify-otp", json={"code": "000000"})
    locked = otp_client.post("/verify-otp", json={"code": "000000"})
    assert locked.status_code == 429 and locked.get_json().get("restart") is True    # terminal -> route back


def test_verify_otp_without_a_pending_login_signals_restart(otp_client):
    r = otp_client.post("/verify-otp", json={"code": "000000"})                       # no pending challenge
    assert r.status_code == 400 and r.get_json().get("restart") is True
