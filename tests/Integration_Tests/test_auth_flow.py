"""Integration tests for F1 auth over the Flask test client (in-memory user store injected).

The real HTTP flow: register -> login -> session-gated `/me` -> logout. OWNER: Lior.
"""


def _register(client, username="alice", password="s3cretpw!", email=None):
    return client.post("/register", json={"username": username, "password": password,
                                          "email": email or f"{username.strip()}@example.com"})


def _login(client, username="alice", password="s3cretpw!"):
    return client.post("/login", json={"username": username, "password": password})


def test_auth_config_exposes_validator_bounds(client, auth_module):
    """The sign-up form reads its length hints from this endpoint, so the numbers it shows come from the same constants the server enforces — a user is never told a rule the server does not apply."""
    data = client.get("/auth/config").get_json()
    assert data["username_min"] == auth_module.USERNAME_MIN
    assert data["username_max"] == auth_module.USERNAME_MAX
    assert data["password_min"] == auth_module.PASSWORD_MIN
    assert data["password_max"] == auth_module.PASSWORD_MAX
    assert data["email_mode"] == "mock"                          # no SMTP in tests -> mock (codes on-screen)
    assert "otp_login" in data and "verify_email" in data        # the modes the debug tools panel reads


def test_auth_config_reports_live_when_smtp_set(make_otp_client, fake_users):
    """With a relay configured the endpoint reports that codes really are emailed, so the interface never tells someone to look on screen for a code that went to their inbox."""
    live = make_otp_client(fake_users, SMTP_HOST="smtp.example.com")
    assert live.get("/auth/config").get_json()["email_mode"] == "live"


def test_auth_config_follows_a_bound_change(client, auth_module, monkeypatch):
    """Changing the validator changes what the endpoint reports, which proves it reads the live constants rather than a hardcoded copy that can drift."""
    monkeypatch.setattr(auth_module, "PASSWORD_MAX", 999)
    assert client.get("/auth/config").get_json()["password_max"] == 999


# (The happy-path round trips that used to open this file — register 201, login 200, register->login->/me,
#  logout ends the session, and "login before register is 401" — were each removed after measuring that
#  the behaviour they pinned is caught by NAMED tests elsewhere. Returning 200 from /register fails 15
#  tests across five files; renaming the account in the /login body fails
#  test_collided_name_account_signs_in_by_email_to_the_right_account; a /logout that does not clear the
#  session fails test_parts_in_isolation.py::test_auth_works_with_only_the_user_store and
#  test_elad_lane_journey.py::test_the_lane_is_fully_auth_gated_when_the_session_ends; and answering 200
#  to an unknown user fails test_auth.py::test_unknown_user_and_wrong_password_are_indistinguishable.
#  What remains here is what only this file proves.)


def test_login_replaces_the_whole_session_rather_than_adding_to_it(client):
    """Logging in WIPES the session it inherits, so nothing planted in the browser beforehand — and no
    fragment of whoever was signed in before — survives into the new login.

    That wipe is the defence against session fixation: without it, an attacker who can seed a value in
    the victim's session keeps it there across the victim's login. Checking the username alone could
    never see the difference, because the username is overwritten either way — measured: deleting
    `session.clear()` from the login route left the whole suite green (measured).
    """
    _register(client, "alice", "s3cretpw!")
    _register(client, "bob", "s3cretpw!")
    _login(client, "alice", "s3cretpw!")
    with client.raw.session_transaction() as sess:
        sess["planted"] = "attacker-controlled"        # anything already in the session before login
    _login(client, "bob", "s3cretpw!")
    assert client.get("/me").get_json()["username"] == "bob"
    with client.raw.session_transaction() as sess:
        assert "planted" not in sess, "login must clear the session it inherits, not add to it"


def test_logout_without_login_is_idempotent(client):
    """Logging out when not signed in succeeds quietly, so a stale tab clicking log-out does not surface an error to someone who is already out."""
    assert client.post("/logout").status_code == 200


# (GET /login -> 405 is proven by test_error_handlers.py::test_wrong_method_returns_json_405, which
#  makes the same request against the same route and additionally pins the JSON shape of the reply.
#  Measured: opening /login to GET fails both, so this file's copy added nothing.)


def test_the_handle_keeps_the_capitalisation_the_user_typed(client):
    """Two people who type the same name with different capitalisation each keep the case they chose, so
    a handle is never quietly folded into somebody else's.

    Asserting only that both registrations return 201 — which is what this test used to do — proves
    nothing about capitalisation: the two accounts have different emails, so they both succeed either
    way. Measured: lower-casing the display name before allocating the handle left the whole suite green
    (measured), and under it the second account's handle comes back "alice-2" instead of "Alice".
    The exact handles are what has to be pinned.
    """
    first = _register(client, "alice", "s3cretpw!", email="alice@example.com")
    second = _register(client, "Alice", "s3cretpw!", email="alice2@example.com")
    assert first.get_json()["username"] == "alice"
    assert second.get_json()["username"] == "Alice", "the handle must keep the case the user typed"


def test_register_rejects_a_duplicate_email(client):
    """One email means one account, because password reset looks the user up by email and a shared address would make the reset ambiguous.

    The check is case- and whitespace-insensitive, so a second registration cannot slip through by typing the same address differently.
    """
    assert _register(client, "alice", email="dup@example.com").status_code == 201
    resp = _register(client, "bob", email="  DUP@Example.com ")
    assert resp.status_code == 409
    assert "email" in resp.get_json()["error"].lower()


def test_login_accepts_email_as_identifier(client):
    """Someone can sign in with the email they registered with, not only the name they chose — most people remember one but not the other.

    The exact status is pinned rather than a range, so a regression to "email is not a valid identifier" fails here instead of passing as an acceptable 401.
    """
    _register(client, "carol", email="carol@example.com")
    by_email = client.post("/login", json={"username": "Carol@Example.com", "password": "s3cretpw!"})
    # this fixture has OTP off, so the email identifier must log straight in — pinning the exact
    # pair (not `in (200, 401)`) is what makes a regression to "email is not a valid identifier" fail.
    assert by_email.status_code == 200, by_email.get_json()
    assert by_email.get_json()["status"] == "logged in"


# (The "production default store still boots + serves /health without Mongo" case is asserted
#  byte-identically by test_web_smoke.py::test_web_boots_and_serves_health, which is its natural
#  home and the one the REPORT's smoke row cites.)


# ---- identity model: display name is NON-unique; each account gets a unique internal handle ----
def test_duplicate_display_name_is_allowed_with_distinct_emails(client):
    """Two people may both call themselves the same thing: they share a display name but get separate accounts and separate internal handles."""
    r1 = _register(client, "alex", email="alex1@example.com")
    r2 = _register(client, "alex", email="alex2@example.com")
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.get_json()["display_name"] == "alex" == r2.get_json()["display_name"]  # same shown name
    assert r1.get_json()["username"] != r2.get_json()["username"]                    # distinct handles


def test_handle_gets_a_suffix_on_display_name_collision(client):
    """Each colliding name gets its own suffixed handle, so the accounts stay individually addressable no matter how many people pick the same name."""
    assert _register(client, "sam", email="s1@example.com").get_json()["username"] == "sam"
    assert _register(client, "sam", email="s2@example.com").get_json()["username"] == "sam-2"
    assert _register(client, "sam", email="s3@example.com").get_json()["username"] == "sam-3"


# (test_me_exposes_the_display_name was removed: its account was registered as "alex", so its handle and
#  its display name were the SAME string and the assertion held even when /me returned the raw handle —
#  measured, it did not fail its own mutation. The property is proven by
#  test_account_editing.py::test_change_display_name_updates_shown_name_but_not_the_handle, where the two
#  deliberately differ.)


def test_me_returns_only_the_three_public_session_fields(client):
    """/me answers with exactly username, display_name and email_consent — an allowlist, so a field added to the user record can never ride along to the browser.

    Every other test of this route reads a single key, which means none of them can notice an EXTRA
    key appearing. Measured before adding this: appending the caller's own `password_hash` to the /me
    payload left the whole suite green (measured). Two neighbours outside auth were already guarded —
    /users/search by test_messages.py::test_user_search_returns_no_pii, and the post detail by the
    like/dislike tallies test — but the auth routes were NOT, which the test below now covers.
    """
    _register(client, "alex", email="alex@example.com")
    _login(client, "alex")
    body = client.get("/me").get_json()
    assert set(body) == {"username", "display_name", "email_consent"}, \
        f"/me must return exactly the three public fields, got {sorted(body)}"


def test_no_auth_route_answers_with_an_unexpected_field(client, make_otp_client, fake_users):
    """Every auth route answers with EXACTLY the fields it documents, so a value added to a user record —
    or read out of the app config — can never ride along to the browser.

    /me got this guard first, one route at a time; the rest of auth had none. Measured: appending
    `leaked=str(current_app.config["SECRET_KEY"])` to the five success payloads in routes/auth.py at once
    (/auth/config, /register, /register/verify, /login, /verify-otp) left the whole suite green — 1071
    passed. Each of those routes is read by tests that pull ONE key out of the body, and reading one key
    can never notice an extra one. /auth/config is the sharpest of the five: it is unauthenticated.
    """
    account = {"status", "username", "display_name"}     # what the four account routes answer with

    assert set(client.get("/auth/config").get_json()) == {
        "username_min", "username_max", "password_min", "password_max",
        "email_mode", "email_debug_toggle", "otp_login", "verify_email"}

    assert set(_register(client).get_json()) == account
    assert set(_login(client).get_json()) == account

    # the two-step routes need their features ON, so each gets a client configured for it
    verify = make_otp_client(fake_users, REGISTER_VERIFY_EMAIL=True)
    code = verify.post("/register", json={"username": "bob", "password": "s3cretpw!",
                                          "email": "bob@example.com"}).get_json()["dev_code"]
    assert set(verify.post("/register/verify", json={"code": code}).get_json()) == account

    otp = make_otp_client(fake_users)                    # same store -> bob already exists
    otp_code = otp.post("/login", json={"username": "bob", "password": "s3cretpw!"}).get_json()["dev_otp"]
    assert set(otp.post("/verify-otp", json={"code": otp_code}).get_json()) == account


def test_collided_name_account_signs_in_by_email_to_the_right_account(client):
    """A user whose name collided has an internal handle they never see, so they sign in by EMAIL — and must land on THEIR account, not on the first person who took the name."""
    _register(client, "sam", email="sam1@example.com")
    _register(client, "sam", email="sam2@example.com")             # internal handle "sam-2"
    resp = client.post("/login", json={"username": "sam2@example.com", "password": "s3cretpw!"})
    assert resp.status_code == 200
    assert resp.get_json()["display_name"] == "sam"                # shown name
    assert resp.get_json()["username"] == "sam-2"                  # the distinct handle, not the first "sam"
