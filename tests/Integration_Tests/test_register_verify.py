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


def test_register_rejects_a_duplicate_email_before_verifying(verify_client, fake_users):
    fake_users.add("existing", "hash", email="taken@example.com")
    assert _start(verify_client, email="taken@example.com").status_code == 409   # caught up front, no code sent


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
