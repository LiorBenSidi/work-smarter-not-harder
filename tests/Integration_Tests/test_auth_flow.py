"""Integration tests for F1 auth over the Flask test client (in-memory user store injected).

The real HTTP flow: register -> login -> session-gated `/me` -> logout. OWNER: Lior.
"""


def _register(client, username="alice", password="s3cretpw!"):
    return client.post("/register", json={"username": username, "password": password})


def _login(client, username="alice", password="s3cretpw!"):
    return client.post("/login", json={"username": username, "password": password})


def test_register_returns_201(client):
    resp = _register(client)
    assert resp.status_code == 201
    assert resp.get_json()["username"] == "alice"


def test_register_duplicate_returns_409(client):
    _register(client)
    assert _register(client).status_code == 409


def test_login_with_valid_credentials_returns_200(client):
    _register(client)
    resp = _login(client)
    assert resp.status_code == 200
    assert resp.get_json()["username"] == "alice"


def test_login_before_register_returns_401(client):
    assert _login(client).status_code == 401


def test_me_requires_login(client):
    assert client.get("/me").status_code == 401


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
