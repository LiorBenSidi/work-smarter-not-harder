"""Integration tests for 2-step login verification (email OTP + remember-this-browser). OWNER: Lior (F1).

These run with OTP ACTIVE (the `otp_client` / `make_otp_client` fixtures set OTP_ENABLED on + TESTING off,
SMTP unset so the code is dev-surfaced) — the classic one-step flow is covered by test_auth_flow.py and
its TESTING gate is regression-guarded here too.

Security bar: the code is stored only as a werkzeug hash, expires, locks out after N wrong guesses, is
bound to the browser session that requested it, and the remember cookie is signed + HttpOnly + tied to
the password hash so a password change revokes it. Storing a code in plaintext, issuing a raw
(unsigned) trust token, or dropping the Secure flag would each break one of those properties.
"""
import re

PW = "s3cretpw!"


def _register(client, username="alice", password=PW, email=None):
    return client.post("/register", json={"username": username, "password": password,
                                          "email": email or f"{username}@example.com"})


def _login(client, username="alice", password=PW):
    return client.post("/login", json={"username": username, "password": password})


def test_login_returns_otp_required_when_active(otp_client):
    """A correct password alone does NOT grant a session when second-step verification is on — it only earns the right to be asked for the code."""
    _register(otp_client)
    body = _login(otp_client).get_json()
    assert body["status"] == "otp_required" and body["username"] == "alice"
    assert otp_client.get("/me").status_code == 401           # password alone does NOT grant a session


def test_dev_otp_surfaced_without_smtp_and_verifies(otp_client):
    """With no relay configured the code is surfaced in the response so the flow is usable in development, and verifying it genuinely completes the sign-in."""
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]           # dev/no-SMTP -> code surfaced in the response
    assert re.fullmatch(r"\d{6}", code)
    v = otp_client.post("/verify-otp", json={"code": code})
    assert v.status_code == 200 and v.get_json()["status"] == "logged in"
    assert otp_client.get("/me").get_json()["username"] == "alice"


def test_otp_not_surfaced_when_smtp_configured(make_otp_client, fake_users, auth_module, monkeypatch):
    """As soon as a relay is configured the code stops appearing in the response and leaves only by email — otherwise anyone who can see the response can complete somebody else's sign-in."""
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
    """A peek at the stored record reveals only a hash, never the live code — so a database leak does not hand over working second factors."""
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]
    stored = fake_users._by_name["alice"]["otp_hash"]
    assert code not in stored and stored.startswith(("pbkdf2:", "scrypt:", "argon2"))


def test_wrong_code_rejected_then_locks_out(otp_client):
    """Wrong guesses are refused and then locked out, so a six-digit code cannot simply be enumerated.

    The lockout clears the pending challenge too, forcing a fresh sign-in rather than leaving a half-open one.
    """
    _register(otp_client)
    _login(otp_client)
    for _ in range(4):                                        # OTP_MAX_ATTEMPTS=5: first four are 401
        r = otp_client.post("/verify-otp", json={"code": "000000"})
        assert r.status_code == 401 and r.get_json()["error"] == "incorrect code"
    assert otp_client.post("/verify-otp", json={"code": "000000"}).status_code == 429   # 5th -> lockout
    # challenge + pending session cleared -> must start a fresh login
    assert otp_client.post("/verify-otp", json={"code": "000000"}).status_code == 400


def test_expired_code_is_rejected(otp_client, fake_users):
    """A code past its lifetime is refused EVEN WHEN IT IS THE RIGHT CODE, so one intercepted long ago is worthless.

    The right code is the whole point: an expired challenge rejects a wrong guess anyway, on the
    incorrect-code path, so submitting "000000" here proved only that a wrong code fails. Measured with
    the wrong code: making the TTL gate honour any CORRECT code — `if expired and not
    check_password_hash(...)` — left the whole suite green (measured), i.e. an intercepted code would
    still have worked a week later and nothing would have said so.
    """
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]           # the REAL code for this challenge
    fake_users._by_name["alice"]["otp_expires_at"] = 0        # force the stored challenge past its TTL
    r = otp_client.post("/verify-otp", json={"code": code})
    assert r.status_code == 400 and "expired" in r.get_json()["error"]
    assert otp_client.get("/me").status_code == 401           # and it granted no session on the way out


def test_a_challenge_already_at_max_attempts_is_locked_out(otp_client, fake_users):
    """A challenge whose counter is already at the limit is refused before the code is even checked, so a
    concurrent burst of guesses cannot slip a late arrival past the lockout.

    The attempt counter is bumped ATOMICALLY in the store, so two requests in flight together can both
    read "not locked yet", and the second one lands with the counter already at the cap — the state this
    reproduces by setting it directly. The wrong-code path has its own lockout (covered by
    test_wrong_code_rejected_then_locks_out); this is the entry gate, and deleting it left the whole
    suite green (measured) because every existing test arrives with a counter below the cap.
    """
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]
    max_attempts = otp_client.raw.application.config["OTP_MAX_ATTEMPTS"]
    fake_users._by_name["alice"]["otp_attempts"] = max_attempts   # a concurrent burst got there first
    r = otp_client.post("/verify-otp", json={"code": code})       # even the CORRECT code is now refused
    assert r.status_code == 429 and r.get_json().get("restart") is True
    assert otp_client.get("/me").status_code == 401


def test_remember_this_browser_skips_otp_next_login(otp_client):
    """A browser the user chose to trust is not challenged again, which is what keeps the second step from becoming a daily tax."""
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]
    otp_client.post("/verify-otp", json={"code": code, "remember": True})
    r2 = _login(otp_client).get_json()                        # same, now-trusted browser
    assert r2["status"] == "logged in" and "dev_otp" not in r2


def test_remember_cookie_is_signed_and_httponly(otp_client):
    """The trust cookie is unreadable from JavaScript and genuinely SIGNED, so it cannot be forged into a bypass.

    The signature half went unasserted before: nothing here would have failed if the cookie had carried a raw, unsigned value.
    """
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]
    v = otp_client.post("/verify-otp", json={"code": code, "remember": True})
    set_cookie = v.headers.get("Set-Cookie", "")
    assert "remember_token=" in set_cookie and "HttpOnly" in set_cookie
    # ...and actually assert the SIGNED half of this test's name, which went unchecked: nothing here
    # would have failed if the cookie carried a raw, unsigned value. An itsdangerous token is
    # `payload.timestamp.signature`, so an unsigned one has no separators.
    token = set_cookie.split("remember_token=", 1)[1].split(";", 1)[0]
    assert token.count(".") == 2, f"the remember token must be signed (payload.ts.sig), got: {token!r}"


def test_no_remember_flag_sets_no_cookie_and_still_prompts(otp_client):
    """Not asking to be remembered means no trust cookie and a challenge next time — the choice is honoured in both directions."""
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]
    v = otp_client.post("/verify-otp", json={"code": code})   # remember omitted
    assert "remember_token" not in v.headers.get("Set-Cookie", "")
    assert _login(otp_client).get_json()["status"] == "otp_required"


def test_password_change_invalidates_remember_cookie(otp_client, fake_users, auth_module):
    """Changing the password revokes every remembered browser, so someone locking an intruder out is not left with a trusted device still walking straight in."""
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]
    otp_client.post("/verify-otp", json={"code": code, "remember": True})
    fake_users.set_password("alice", auth_module.generate_password_hash("N3wpassword!"))
    # the embedded password-hash tail no longer matches -> the trusted browser must re-verify
    assert otp_client.post("/login", json={"username": "alice", "password": "N3wpassword!"}
                           ).get_json()["status"] == "otp_required"


def test_logout_clears_remember_cookie(otp_client):
    """Logging out withdraws trust in that browser, so signing out on a shared machine actually undoes the decision to skip verification there."""
    _register(otp_client)
    code = _login(otp_client).get_json()["dev_otp"]
    otp_client.post("/verify-otp", json={"code": code, "remember": True})
    otp_client.post("/logout")                                # withdraws trust in this browser
    assert _login(otp_client).get_json()["status"] == "otp_required"


def test_verify_otp_is_bound_to_the_session_user(make_otp_client, fake_users):
    """A code issued to one browser cannot be redeemed from another that never started that sign-in — so an intercepted code is useless without the session it belongs to.

    The attacker NAMES the victim in the request body, which is the only version of this attack worth
    testing: an empty body is refused by the "no verification in progress" branch no matter where the
    route reads its user from, so the earlier version passed against a route that would happily have
    taken the username from the body. Measured: `session.get("pending_otp_user")` changed to read the
    body first left the whole suite green (measured) — an intercepted code would then have completed
    SOMEBODY ELSE'S login from a browser that never started it.
    """
    _register(make_otp_client(fake_users), "alice")
    victim = make_otp_client(fake_users)
    code = victim.post("/login", json={"username": "alice", "password": PW}).get_json()["dev_otp"]
    attacker = make_otp_client(fake_users)                    # fresh browser, no pending_otp_user
    r = attacker.post("/verify-otp", json={"code": code, "username": "alice"})   # names the victim
    assert r.status_code == 400
    assert attacker.get("/me").status_code == 401             # and got no session out of it


def test_otp_is_off_under_testing(client):
    """The gate that keeps the one-step flow available for the rest of the suite still works, so turning verification on for these tests does not silently turn it on everywhere."""
    client.post("/register", json={"username": "alice", "password": PW, "email": "alice@example.com"})
    r = client.post("/login", json={"username": "alice", "password": PW}).get_json()
    assert r["status"] == "logged in" and "dev_otp" not in r


def test_verify_otp_terminal_errors_signal_restart(otp_client):
    """A wrong code is recoverable and leaves the user on the code form; a lockout is TERMINAL and tells the client to route back to sign-in.

    Without that distinction someone locked out is stranded on a form that can never succeed.
    """
    _register(otp_client)
    _login(otp_client)
    wrong = otp_client.post("/verify-otp", json={"code": "000000"})
    assert wrong.status_code == 401 and not wrong.get_json().get("restart")          # recoverable -> stay
    for _ in range(3):
        otp_client.post("/verify-otp", json={"code": "000000"})
    locked = otp_client.post("/verify-otp", json={"code": "000000"})
    assert locked.status_code == 429 and locked.get_json().get("restart") is True    # terminal -> route back


def test_verify_otp_without_a_pending_login_signals_restart(otp_client):
    """Submitting a code with no sign-in in progress tells the client to start over rather than leaving it on a form with nothing behind it."""
    r = otp_client.post("/verify-otp", json={"code": "000000"})                       # no pending challenge
    assert r.status_code == 400 and r.get_json().get("restart") is True
