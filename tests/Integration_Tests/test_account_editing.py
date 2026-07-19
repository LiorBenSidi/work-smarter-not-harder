"""Account settings — change display name / change password from inside the app. OWNER: Lior.

Covers the two /account endpoints: display-name change (validation + NoSQL-injection gate +
handle-stability) and password change (current-password gate + new-password validation + the
"remember this browser" revocation that forces OTP again on the next login). Runs on the in-memory
FakeUsers store (no Mongo) via the shared fixtures.
"""


def _register_and_login(client, name="alice", password="password123", email=None):
    """Register `name` and log them in (OTP is off under the default TESTING client). Returns the handle."""
    email = email or f"{name}@ex.com"
    reg = client.post("/register", json={"username": name, "password": password, "email": email})
    assert reg.status_code == 201
    r = client.post("/login", json={"username": name, "password": password})
    assert r.status_code == 200 and r.get_json()["status"] == "logged in"
    return r.get_json()["username"]


# ---- display name ----
def test_change_display_name_updates_shown_name_but_not_the_handle(client):
    _register_and_login(client)
    r = client.post("/account/display-name", json={"display_name": "Alice Cooper"})
    assert r.status_code == 200
    assert r.get_json()["display_name"] == "Alice Cooper"
    me = client.get("/me").get_json()
    assert me["display_name"] == "Alice Cooper"
    assert me["username"] == "alice"   # the internal handle (ownership/DM/history key) is untouched


def test_display_name_is_trimmed(client):
    _register_and_login(client)
    r = client.post("/account/display-name", json={"display_name": "   Spacey   "})
    assert r.status_code == 200 and r.get_json()["display_name"] == "Spacey"


def test_change_display_name_rejects_non_string_injection(client):
    # the string-type check is the NoSQL-injection gate — a {"$gt": ""} object never reaches a query.
    _register_and_login(client)
    r = client.post("/account/display-name", json={"display_name": {"$gt": ""}})
    assert r.status_code == 400


def test_change_display_name_rejects_out_of_bounds(client):
    _register_and_login(client)
    assert client.post("/account/display-name", json={"display_name": "ab"}).status_code == 400        # too short
    assert client.post("/account/display-name", json={"display_name": "x" * 65}).status_code == 400     # too long


# ---- auth gate ----
def test_account_endpoints_require_authentication(client):
    # no session -> 401 on both (the login_required gate), no store mutation possible
    assert client.post("/account/display-name", json={"display_name": "Bob"}).status_code == 401
    assert client.post("/account/password",
                       json={"current_password": "x", "new_password": "y" * 8}).status_code == 401


# ---- password ----
def test_change_password_rejects_wrong_current(client):
    _register_and_login(client, password="password123")
    r = client.post("/account/password", json={"current_password": "WRONGpass1", "new_password": "newpassword1"})
    assert r.status_code == 403
    # the password is unchanged: the original still logs in
    client.post("/logout")
    assert client.post("/login", json={"username": "alice", "password": "password123"}).status_code == 200


def test_change_password_success_swaps_the_credential(client):
    _register_and_login(client, password="password123")
    r = client.post("/account/password", json={"current_password": "password123", "new_password": "newpassword1"})
    assert r.status_code == 200
    client.post("/logout")
    assert client.post("/login", json={"username": "alice", "password": "password123"}).status_code == 401  # old dead
    assert client.post("/login", json={"username": "alice", "password": "newpassword1"}).status_code == 200  # new live


def test_change_password_rejects_short_new(client):
    _register_and_login(client, password="password123")
    r = client.post("/account/password", json={"current_password": "password123", "new_password": "short"})
    assert r.status_code == 400


def test_change_password_rejects_non_string_injection(client):
    _register_and_login(client, password="password123")
    r = client.post("/account/password", json={"current_password": {"$ne": ""}, "new_password": "newpassword1"})
    assert r.status_code == 400


def test_change_password_clears_this_browsers_remember_cookie(client):
    _register_and_login(client, password="password123")
    r = client.post("/account/password", json={"current_password": "password123", "new_password": "newpassword1"})
    # the response expires this browser's remember cookie (belt-and-suspenders alongside the hash-tail
    # invalidation) so this device also re-verifies on its next login.
    remember = [c for c in r.headers.get_all("Set-Cookie") if c.startswith("remember_token=")]
    assert remember, "the response must act on this browser's remember cookie"
    # `"remember_token=" in set_cookies` alone is NOT enough: a response handing back a fresh, VALID
    # cookie matches it just as well — the exact inverse of the property this test is named for.
    # Pin the expiry that actually clears it.
    cleared = remember[0]
    assert cleared.startswith("remember_token=;"), f"the cookie value must be emptied, got: {cleared}"
    assert "Expires=Thu, 01 Jan 1970" in cleared or "Max-Age=0" in cleared, cleared


def test_password_change_forces_reverification_on_next_login(otp_client):
    """Security: a password change revokes 'remember this browser' -> the next login needs OTP again.

    Uses the OTP-active client: pass OTP once with remember=True (this browser is now trusted and skips
    OTP), change the password, then confirm the next login is challenged again — the remember trust was
    revoked (the cookie embeds the old password-hash tail, which no longer matches)."""
    otp_client.post("/register", json={"username": "alice", "password": "password123", "email": "a@ex.com"})
    r = otp_client.post("/login", json={"username": "alice", "password": "password123"})
    code = r.get_json()["dev_otp"]
    otp_client.post("/verify-otp", json={"code": code, "remember": True})
    # sanity: the browser is now trusted -> a re-login skips OTP
    trusted = otp_client.post("/login", json={"username": "alice", "password": "password123"})
    assert trusted.get_json()["status"] == "logged in"
    # change the password from the authenticated session
    changed = otp_client.post("/account/password",
                              json={"current_password": "password123", "new_password": "newpassword1"})
    assert changed.status_code == 200
    # next login with the NEW password is challenged again -> remember trust was revoked
    after = otp_client.post("/login", json={"username": "alice", "password": "newpassword1"})
    assert after.get_json()["status"] == "otp_required"
