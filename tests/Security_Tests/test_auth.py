"""MANDATORY auth/security tests — OWNER: Lior (F1). Required by the rubric (docs/FEEDBACK.md) + DESIGN §5.

Adversarial: a stored password must be a werkzeug hash (never plaintext); bad / injection inputs must
never authenticate or reach a query; login must not leak which half was wrong (no user-enumeration);
gated endpoints reject the unauthenticated. In-memory user store injected (no Mongo) — see conftest.
"""


def _register(client, username="alice", password="s3cretpw!"):
    return client.post("/register", json={"username": username, "password": password, "email": f"{username}@example.com"})


def test_password_is_hashed_not_plaintext(client, fake_users):
    _register(client, "alice", "s3cretpw!")
    stored = fake_users.get("alice")["password_hash"]
    assert stored != "s3cretpw!"             # never the plaintext
    assert "s3cretpw!" not in stored
    assert stored.startswith(("pbkdf2:", "scrypt:"))   # a werkzeug hash


def test_unknown_user_and_wrong_password_are_indistinguishable(client):
    # no user-enumeration: same status + same body whether the user is missing or the password is wrong
    _register(client, "alice", "s3cretpw!")
    wrong_pw = client.post("/login", json={"username": "alice", "password": "wrongpass1"})
    no_user = client.post("/login", json={"username": "ghost", "password": "s3cretpw!"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.get_json() == no_user.get_json()


# (GET /me auth-gating is covered by the Negative_Tests 13-route matrix — same route, same fixture.
#  The injection tests below stay: they pin the EXACT 400, where that matrix accepts any 4xx.)


def test_nosql_injection_login_payload_rejected(client):
    # {"username": {"$gt": ""}} must be rejected as malformed input, never run as a query
    resp = client.post("/login", json={"username": {"$gt": ""}, "password": {"$gt": ""}})
    assert resp.status_code == 400


def test_nosql_injection_cannot_register(client):
    resp = client.post("/register", json={"username": {"$ne": None}, "password": "s3cretpw!"})
    assert resp.status_code == 400


def test_non_json_body_returns_400(client):
    resp = client.post("/login", data="not json", content_type="text/plain")
    assert resp.status_code == 400


class _BrokenUsers:
    """A user store that fails on every call — exercises the graceful-degradation (503) path."""

    def get(self, username):
        raise RuntimeError("store down")

    def add(self, username, password_hash):
        raise RuntimeError("store down")


def test_register_degrades_to_503_when_store_fails(make_client):
    resp = make_client(_BrokenUsers()).post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    assert resp.status_code == 503


def test_login_degrades_to_503_when_store_fails(make_client):
    resp = make_client(_BrokenUsers()).post("/login", json={"username": "alice", "password": "s3cretpw!"})
    assert resp.status_code == 503


def test_me_degrades_to_503_when_store_fails(client, fake_users, monkeypatch):
    # /me was an unguarded 500 on a store hiccup; it must degrade to 503 like every other route.
    _register(client, "alice", "s3cretpw!")
    client.post("/login", json={"username": "alice", "password": "s3cretpw!"})   # session established first
    def boom(*a, **k):
        raise RuntimeError("store down")
    monkeypatch.setattr(fake_users, "get_email_consent", boom)                    # now the store hiccups
    assert client.get("/me").status_code == 503


def test_same_password_yields_different_hashes(client, fake_users):
    # werkzeug salts each hash -> two users with the same password must not share a hash
    _register(client, "alice", "samePassw0rd")
    _register(client, "bob", "samePassw0rd")
    assert fake_users.get("alice")["password_hash"] != fake_users.get("bob")["password_hash"]


def test_login_with_unknown_user_still_verifies_a_hash(client, auth_module, monkeypatch):
    # constant-time defense: the missing-user path must still run a password check (no timing oracle)
    seen = []
    real = auth_module.check_password_hash
    monkeypatch.setattr(auth_module, "check_password_hash", lambda h, p: seen.append(h) or real(h, p))
    client.post("/login", json={"username": "ghost", "password": "whatever12"})
    assert seen, "expected a hash verification even when the user does not exist"
