"""Integration tests for F2 profile over the Flask client (in-memory stores). OWNER: Lior."""


def _login(c, username="alice"):
    c.post("/register", json={"username": username, "password": "s3cretpw!", "email": f"{username}@example.com"})
    c.post("/login", json={"username": username, "password": "s3cretpw!"})


def _profile():
    return {"age": 30, "gender": "male", "height": 180, "weight": 80, "goal": "maintain", "training_frequency": 3}


def test_get_profile_before_save_is_null(profile_client):
    _login(profile_client)
    resp = profile_client.get("/profile")
    assert resp.status_code == 200
    assert resp.get_json()["profile"] is None


def test_save_then_get_profile_roundtrip(profile_client):
    _login(profile_client)
    assert profile_client.post("/profile", json=_profile()).status_code == 200
    # the WHOLE profile must survive the round-trip: asserting only age+goal let a mutation that
    # dropped height / weight / gender / training_frequency on save pass unnoticed.
    got = profile_client.get("/profile").get_json()["profile"]
    assert {k: got[k] for k in _profile()} == _profile()


def test_save_invalid_profile_returns_400(profile_client):
    _login(profile_client)
    bad = _profile()
    bad["age"] = "old"
    assert profile_client.post("/profile", json=bad).status_code == 400


def test_profile_is_per_user(profile_client):
    # alice saves; bob (a different session) must not see alice's profile
    _login(profile_client, "alice")
    profile_client.post("/profile", json=_profile())
    profile_client.post("/logout")
    _login(profile_client, "bob")
    assert profile_client.get("/profile").get_json()["profile"] is None
