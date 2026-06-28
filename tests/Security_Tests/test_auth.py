"""MANDATORY auth/security tests — OWNER: Lior (F1). Required by the rubric (docs/FEEDBACK.md) + DESIGN §5.

Adversarial: a stored password must be a werkzeug hash (never plaintext); bad / injection inputs must
never authenticate or reach a query; login must not leak which half was wrong (no user-enumeration);
gated endpoints reject the unauthenticated. In-memory user store injected (no Mongo) — see conftest.
"""


def _register(client, username="alice", password="s3cretpw!"):
    return client.post("/register", json={"username": username, "password": password})


def test_password_is_hashed_not_plaintext(client, fake_users):
    _register(client, "alice", "s3cretpw!")
    stored = fake_users.get("alice")["password_hash"]
    assert stored != "s3cretpw!"             # never the plaintext
    assert "s3cretpw!" not in stored
    assert stored.startswith(("pbkdf2:", "scrypt:"))   # a werkzeug hash


def test_wrong_password_returns_401(client):
    _register(client, "alice", "s3cretpw!")
    resp = client.post("/login", json={"username": "alice", "password": "wrongpass1"})
    assert resp.status_code == 401


def test_unknown_user_and_wrong_password_are_indistinguishable(client):
    # no user-enumeration: same status + same body whether the user is missing or the password is wrong
    _register(client, "alice", "s3cretpw!")
    wrong_pw = client.post("/login", json={"username": "alice", "password": "wrongpass1"})
    no_user = client.post("/login", json={"username": "ghost", "password": "s3cretpw!"})
    assert wrong_pw.status_code == no_user.status_code == 401
    assert wrong_pw.get_json() == no_user.get_json()


def test_protected_endpoint_without_login_returns_401(client):
    assert client.get("/me").status_code == 401


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
