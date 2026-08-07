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
    """Registration creates NOTHING until the emailed code is confirmed, so nobody can take an account on an address they do not control."""
    r = _start(verify_client)
    body = r.get_json()
    assert r.status_code == 200 and body["status"] == "verify_required" and body["email"] == "alice@example.com"
    assert "dev_code" in body                                    # no SMTP -> code surfaced in the response
    # the account does NOT exist yet -> login can't succeed
    assert verify_client.post("/login", json={"username": "alice@example.com", "password": PW}).status_code == 401


def test_register_verify_creates_account_and_signs_in(verify_client):
    """Confirming the code creates the account and signs the person straight in, so proving the address is not an extra hurdle on top of a separate login."""
    code = _start(verify_client).get_json()["dev_code"]
    r = verify_client.post("/register/verify", json={"code": code})
    body = r.get_json()
    assert r.status_code == 201 and body["status"] == "registered" and body["display_name"] == "Alice"
    assert verify_client.get("/me").status_code == 200           # verified email -> signed straight in


def test_register_verify_rejects_a_wrong_code(verify_client):
    """A wrong code creates no account and grants no session — a failed verification leaves nothing half-made behind."""
    _start(verify_client)
    assert verify_client.post("/register/verify", json={"code": "000000"}).status_code == 400
    assert verify_client.get("/me").status_code == 401           # no account, not signed in


def test_register_verify_without_a_pending_registration_is_rejected(verify_client):
    """A code submitted with no registration in progress is refused, so the endpoint cannot be used on its own to conjure an account."""
    assert verify_client.post("/register/verify", json={"code": "123456"}).status_code == 400


def test_register_duplicate_email_is_enumeration_safe(make_otp_client, fake_users, auth_module, monkeypatch):
    """A duplicate address must be indistinguishable from a fresh one, so signing up cannot be used to discover who already has an account.

    The existing account is left completely untouched — no code is issued for the duplicate; its owner is notified instead.
    """
    monkeypatch.setattr(auth_module, "send_email_async", lambda *a, **k: True)  # no network/thread; swallows code + notice
    fake_users.add("existing", "hash", email="taken@example.com")
    client = make_otp_client(fake_users, REGISTER_VERIFY_EMAIL=True, SMTP_HOST="smtp.example.com")
    dup = client.post("/register", json={"username": "Bob", "password": PW, "email": "taken@example.com"})
    fresh = client.post("/register", json={"username": "Carol", "password": PW, "email": "new@example.com"})
    assert dup.status_code == fresh.status_code == 200                        # NOT 409 for the duplicate
    assert dup.get_json()["status"] == fresh.get_json()["status"] == "verify_required"
    assert "dev_code" not in dup.get_json() and "dev_code" not in fresh.get_json()   # SMTP set -> never surfaced
    assert "error" not in dup.get_json()                                      # nothing that reveals "taken"


def test_register_equalizes_kdf_work_on_duplicate_email(make_otp_client, fake_users, auth_module, monkeypatch):
    """A duplicate address must not be detectable by response LATENCY either.

    The fresh branch hashes the verification code, so the duplicate branch performs an equal-cost dummy hash — counted here, because a branch that skips expensive work is measurably faster and that timing IS the leak.
    """
    monkeypatch.setattr(auth_module, "send_email_async", lambda *a, **k: True)   # no network/thread
    real = auth_module.generate_password_hash
    calls = {"n": 0}
    monkeypatch.setattr(auth_module, "generate_password_hash",
                        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), real(*a, **k))[1])
    fake_users.add("existing", "hash", email="taken@example.com")
    client = make_otp_client(fake_users, REGISTER_VERIFY_EMAIL=True, SMTP_HOST="smtp.example.com")
    calls["n"] = 0
    client.post("/register", json={"username": "Bob", "password": PW, "email": "taken@example.com"})
    dup_kdf = calls["n"]
    calls["n"] = 0
    client.post("/register", json={"username": "Carol", "password": PW, "email": "new@example.com"})
    fresh_kdf = calls["n"]
    assert dup_kdf == fresh_kdf >= 2, f"duplicate branch does unequal KDF work: dup={dup_kdf} fresh={fresh_kdf}"


def test_register_duplicate_still_409_when_verification_is_off(client, fake_users):
    """With verification off there is no cover story to hide behind, so a duplicate is reported plainly.

    That path is for development and tests; production runs with verification on, where the enumeration-safe behaviour above applies.
    """
    fake_users.add("existing", "hash", email="taken@example.com")
    assert client.post("/register", json={"username": "Bob", "password": PW, "email": "taken@example.com"}
                       ).status_code == 409


def test_register_verify_locks_out_after_max_attempts(verify_client):
    """Repeated wrong codes lock the attempt out, so a six-digit code cannot be brute-forced into a free account on someone else's address."""
    _start(verify_client)
    for _ in range(5):                                           # OTP_MAX_ATTEMPTS wrong tries
        assert verify_client.post("/register/verify", json={"code": "000000"}).status_code == 400
    assert verify_client.post("/register/verify", json={"code": "000000"}).status_code == 429   # then locked out


def test_register_resend_reissues_a_working_code(verify_client):
    """A resent code genuinely works, so a user whose first email was slow or lost is not stuck restarting the whole signup."""
    _start(verify_client)
    body = verify_client.post("/register/resend", json={}).get_json()
    assert body["status"] == "code_sent" and "dev_code" in body
    assert verify_client.post("/register/verify", json={"code": body["dev_code"]}).status_code == 201


def test_register_409_when_email_race_beats_the_by_email_check(make_client, auth_module):
    """The duplicate pre-check can MISS under a race, and the unique index then rejects the insert.

    That has to surface as an ordinary "already exists" rather than a 503 or a retry loop — modelled with a store whose pre-check misses but whose write raises, which is exactly the real race.
    """
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
    """A wrong code is recoverable and leaves the user on the form; a lockout and a vanished registration are TERMINAL and route the client back to the start.

    Without the distinction, someone locked out is stranded on a form that can never succeed.
    """
    _start(verify_client)
    wrong = verify_client.post("/register/verify", json={"code": "000000"})
    assert wrong.status_code == 400 and not wrong.get_json().get("restart")           # recoverable -> stay
    for _ in range(4):
        verify_client.post("/register/verify", json={"code": "000000"})
    locked = verify_client.post("/register/verify", json={"code": "000000"})
    assert locked.status_code == 429 and locked.get_json().get("restart") is True     # terminal -> route back
    gone = verify_client.post("/register/verify", json={"code": "000000"})            # pending now cleared
    assert gone.status_code == 400 and gone.get_json().get("restart") is True
