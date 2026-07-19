"""Integration tests for F1 auth over the Flask test client (in-memory user store injected).

The real HTTP flow: register -> login -> session-gated `/me` -> logout. OWNER: Lior.
"""


def _register(client, username="alice", password="s3cretpw!", email=None):
    return client.post("/register", json={"username": username, "password": password,
                                          "email": email or f"{username.strip()}@example.com"})


def _login(client, username="alice", password="s3cretpw!"):
    return client.post("/login", json={"username": username, "password": password})


def test_auth_config_exposes_validator_bounds(client, auth_module):
    # public endpoint the UI reads for the credential hints — values come from the validator constants.
    data = client.get("/auth/config").get_json()
    assert data["username_min"] == auth_module.USERNAME_MIN
    assert data["username_max"] == auth_module.USERNAME_MAX
    assert data["password_min"] == auth_module.PASSWORD_MIN
    assert data["password_max"] == auth_module.PASSWORD_MAX
    assert data["email_mode"] == "mock"                          # no SMTP in tests -> mock (codes on-screen)
    assert "otp_login" in data and "verify_email" in data        # the modes the debug tools panel reads


def test_auth_config_reports_live_when_smtp_set(make_otp_client, fake_users):
    # The mock/live switch is SMTP_HOST: with it set, /auth/config must report "live" (so the UI + the
    # debug panel show where codes go). Locks the live branch — the mock branch is asserted above.
    live = make_otp_client(fake_users, SMTP_HOST="smtp.example.com")
    assert live.get("/auth/config").get_json()["email_mode"] == "live"


def test_auth_config_follows_a_bound_change(client, auth_module, monkeypatch):
    # change the validator -> the endpoint follows (proves single source of truth, not a hardcoded copy).
    monkeypatch.setattr(auth_module, "PASSWORD_MAX", 999)
    assert client.get("/auth/config").get_json()["password_max"] == 999


def test_register_returns_201(client):
    resp = _register(client)
    assert resp.status_code == 201
    assert resp.get_json()["username"] == "alice"


def test_login_with_valid_credentials_returns_200(client):
    _register(client)
    resp = _login(client)
    assert resp.status_code == 200
    assert resp.get_json()["username"] == "alice"


def test_login_before_register_returns_401(client):
    assert _login(client).status_code == 401


def test_full_flow_register_login_me(client):
    _register(client)
    _login(client)
    resp = client.get("/me")
    assert resp.status_code == 200
    assert resp.get_json()["username"] == "alice"


def test_logout_clears_session(client):
    _register(client)
    _login(client)
    assert client.get("/me").status_code == 200
    assert client.post("/logout").status_code == 200
    assert client.get("/me").status_code == 401


def test_relogin_as_different_user_replaces_session(client):
    # session.clear() on login must prevent stale-user bleed
    _register(client, "alice", "s3cretpw!")
    _register(client, "bob", "s3cretpw!")
    _login(client, "alice", "s3cretpw!")
    _login(client, "bob", "s3cretpw!")
    assert client.get("/me").get_json()["username"] == "bob"


def test_logout_without_login_is_idempotent(client):
    assert client.post("/logout").status_code == 200


def test_get_on_post_only_route_is_405(client):
    assert client.get("/login").status_code == 405


def test_usernames_are_case_sensitive(client):
    # intended (documented) behavior: distinct case -> distinct accounts. Distinct emails too, since
    # email is now unique per account (case-variant emails would otherwise collide on the shared address).
    assert _register(client, "alice", "s3cretpw!", email="alice@example.com").status_code == 201
    assert _register(client, "Alice", "s3cretpw!", email="alice2@example.com").status_code == 201


def test_register_rejects_a_duplicate_email(client):
    # one email -> one account: forgot-password looks up by email, so a shared email would make reset
    # ambiguous. Case/whitespace-insensitive (validate_email normalizes) — "Alice@ " == "alice@".
    assert _register(client, "alice", email="dup@example.com").status_code == 201
    resp = _register(client, "bob", email="  DUP@Example.com ")
    assert resp.status_code == 409
    assert "email" in resp.get_json()["error"].lower()


def test_login_accepts_email_as_identifier(client):
    # F1 UX: users can sign in with their username OR the email they registered with.
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
    # Two people can both be "alex" — they just get distinct accounts (distinct emails + internal handles).
    r1 = _register(client, "alex", email="alex1@example.com")
    r2 = _register(client, "alex", email="alex2@example.com")
    assert r1.status_code == 201 and r2.status_code == 201
    assert r1.get_json()["display_name"] == "alex" == r2.get_json()["display_name"]  # same shown name
    assert r1.get_json()["username"] != r2.get_json()["username"]                    # distinct handles


def test_handle_gets_a_suffix_on_display_name_collision(client):
    assert _register(client, "sam", email="s1@example.com").get_json()["username"] == "sam"
    assert _register(client, "sam", email="s2@example.com").get_json()["username"] == "sam-2"
    assert _register(client, "sam", email="s3@example.com").get_json()["username"] == "sam-3"


def test_me_exposes_the_display_name(client):
    _register(client, "alex", email="alex@example.com")
    _login(client, "alex")
    assert client.get("/me").get_json()["display_name"] == "alex"


def test_collided_name_account_signs_in_by_email_to_the_right_account(client):
    # the suffixed account has a handle it never sees — it signs in by EMAIL, and lands on ITS account.
    _register(client, "sam", email="sam1@example.com")
    _register(client, "sam", email="sam2@example.com")             # internal handle "sam-2"
    resp = client.post("/login", json={"username": "sam2@example.com", "password": "s3cretpw!"})
    assert resp.status_code == 200
    assert resp.get_json()["display_name"] == "sam"                # shown name
    assert resp.get_json()["username"] == "sam-2"                  # the distinct handle, not the first "sam"
