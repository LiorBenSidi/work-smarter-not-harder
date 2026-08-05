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


def test_save_then_get_keeps_the_training_preferences(profile_client):
    # `equipment` and `split_preference` are optional and were added after the original six, so a
    # save path that quietly dropped them would leave every unit test green — the validator would
    # still return them, they would just never reach the store. F5 (#276) plans from these two
    # values, so the read-back below is the assertion that matters, not the POST echo.
    _login(profile_client)
    payload = {**_profile(), "equipment": ["barbell", "bands"], "split_preference": "upper_lower"}
    assert profile_client.post("/profile", json=payload).status_code == 200
    got = profile_client.get("/profile").get_json()["profile"]
    assert got["equipment"] == ["barbell", "bands"]
    assert got["split_preference"] == "upper_lower"


def test_save_invalid_profile_returns_400(profile_client):
    _login(profile_client)
    bad = _profile()
    bad["age"] = "old"
    assert profile_client.post("/profile", json=bad).status_code == 400


def test_save_rejects_an_unknown_equipment_item(profile_client):
    # the preference rules are proven per-value as a unit; this proves the route is wired to them
    # at all, which the six original fields cannot demonstrate on their behalf.
    _login(profile_client)
    bad = {**_profile(), "equipment": ["barbell", "treadmill"]}
    assert profile_client.post("/profile", json=bad).status_code == 400


def test_profile_is_per_user(profile_client):
    # alice saves; bob (a different session) must not see alice's profile
    _login(profile_client, "alice")
    profile_client.post("/profile", json=_profile())
    profile_client.post("/logout")
    _login(profile_client, "bob")
    assert profile_client.get("/profile").get_json()["profile"] is None
