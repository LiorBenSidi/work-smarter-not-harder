"""Email verification at registration — the account is created ONLY after the emailed code is confirmed,
so a user can't register with a fake or someone else's address. OWNER: Lior.

Runs with the feature ACTIVE: REGISTER_VERIFY_EMAIL on, TESTING off, SMTP unset (so the code is dev-surfaced
in the response, the same way the login-OTP tests read dev_otp). The rest of the suite keeps instant
registration (TESTING / the flag off), so those tests are unaffected.
"""
import pytest

PW = "s3cretpw!"


@pytest.fixture
def verify_client(make_otp_client, fake_users):
    return make_otp_client(fake_users, REGISTER_VERIFY_EMAIL=True)


def _start(client, display="Alice", email="alice@example.com"):
    return client.post("/register", json={"username": display, "password": PW, "email": email})


def test_register_starts_verification_and_creates_no_account(verify_client):
    r = _start(verify_client)
    body = r.get_json()
    assert r.status_code == 200 and body["status"] == "verify_required" and body["email"] == "alice@example.com"
    assert "dev_code" in body                                    # no SMTP -> code surfaced for dev/grading
    # the account does NOT exist yet -> login can't succeed
    assert verify_client.post("/login", json={"username": "alice@example.com", "password": PW}).status_code == 401


def test_register_verify_creates_account_and_signs_in(verify_client):
    code = _start(verify_client).get_json()["dev_code"]
    r = verify_client.post("/register/verify", json={"code": code})
    body = r.get_json()
    assert r.status_code == 201 and body["status"] == "registered" and body["display_name"] == "Alice"
    assert verify_client.get("/me").status_code == 200           # verified email -> signed straight in


def test_register_verify_rejects_a_wrong_code(verify_client):
    _start(verify_client)
    assert verify_client.post("/register/verify", json={"code": "000000"}).status_code == 400
    assert verify_client.get("/me").status_code == 401           # no account, not signed in


def test_register_verify_without_a_pending_registration_is_rejected(verify_client):
    assert verify_client.post("/register/verify", json={"code": "123456"}).status_code == 400


def test_register_duplicate_email_is_enumeration_safe(make_otp_client, fake_users, auth_module, monkeypatch):
    # A duplicate email must NOT be distinguishable from a fresh one in the register response — no 409 that
    # leaks "this email is registered". With SMTP configured (prod), neither surfaces a code, so the two
    # responses match on every enumeration-relevant field. The existing account is left untouched (no code
    # is issued for the duplicate; a notice email goes to the owner instead).
    monkeypatch.setattr(auth_module, "send_email", lambda *a, **k: True)      # no network; swallows code + notice
    fake_users.add("existing", "hash", email="taken@example.com")
    client = make_otp_client(fake_users, REGISTER_VERIFY_EMAIL=True, SMTP_HOST="smtp.example.com")
    dup = client.post("/register", json={"username": "Bob", "password": PW, "email": "taken@example.com"})
    fresh = client.post("/register", json={"username": "Carol", "password": PW, "email": "new@example.com"})
    assert dup.status_code == fresh.status_code == 200                        # NOT 409 for the duplicate
    assert dup.get_json()["status"] == fresh.get_json()["status"] == "verify_required"
    assert "dev_code" not in dup.get_json() and "dev_code" not in fresh.get_json()   # SMTP set -> never surfaced
    assert "error" not in dup.get_json()                                      # nothing that reveals "taken"


def test_register_duplicate_still_409_when_verification_is_off(client, fake_users):
    # With verify OFF (the default TESTING path), there is no verify_required cover, so a duplicate email is
    # still a plain 409 — this path is dev/tests only (prod runs verify ON, which is enumeration-safe above).
    fake_users.add("existing", "hash", email="taken@example.com")
    assert client.post("/register", json={"username": "Bob", "password": PW, "email": "taken@example.com"}
                       ).status_code == 409


def test_register_verify_locks_out_after_max_attempts(verify_client):
    _start(verify_client)
    for _ in range(5):                                           # OTP_MAX_ATTEMPTS wrong tries
        assert verify_client.post("/register/verify", json={"code": "000000"}).status_code == 400
    assert verify_client.post("/register/verify", json={"code": "000000"}).status_code == 429   # then locked out


def test_register_resend_reissues_a_working_code(verify_client):
    _start(verify_client)
    body = verify_client.post("/register/resend", json={}).get_json()
    assert body["status"] == "code_sent" and "dev_code" in body
    assert verify_client.post("/register/verify", json={"code": body["dev_code"]}).status_code == 201


def test_register_409_when_email_race_beats_the_by_email_check(make_client, auth_module):
    # The by_email pre-check can MISS under a race; the users.email unique index then rejects the insert and
    # create_user raises DuplicateEmailError. The route must turn that into a 409 (not a 503, not a retry
    # loop). Modelled with a store whose by_email misses but whose add raises — exactly the real race.
    class _RaceUsers:
        def by_email(self, email):
            return None                                          # the pre-check misses (the race)

        def add(self, *a, **k):
            raise auth_module.DuplicateEmailError("x@e.com")     # the unique index rejects the second insert

    c = make_client(_RaceUsers())
    r = c.post("/register", json={"username": "alex", "password": PW, "email": "x@e.com"})
    assert r.status_code == 409
    assert "already exists" in r.get_json()["error"]


def test_register_verify_terminal_errors_signal_restart(verify_client):
    # A wrong code is recoverable (400, no restart -> stay); a lockout and a missing pending registration are
    # TERMINAL (restart -> the client routes back to register instead of stranding a dead code form).
    _start(verify_client)
    wrong = verify_client.post("/register/verify", json={"code": "000000"})
    assert wrong.status_code == 400 and not wrong.get_json().get("restart")           # recoverable -> stay
    for _ in range(4):
        verify_client.post("/register/verify", json={"code": "000000"})
    locked = verify_client.post("/register/verify", json={"code": "000000"})
    assert locked.status_code == 429 and locked.get_json().get("restart") is True     # terminal -> route back
    gone = verify_client.post("/register/verify", json={"code": "000000"})            # pending now cleared
    assert gone.status_code == 400 and gone.get_json().get("restart") is True
