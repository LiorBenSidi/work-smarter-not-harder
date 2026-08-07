"""Integration tests for F2 profile over the Flask client (in-memory stores). OWNER: Lior."""


def _login(c, username="alice"):
    c.post("/register", json={"username": username, "password": "s3cretpw!", "email": f"{username}@example.com"})
    c.post("/login", json={"username": username, "password": "s3cretpw!"})


def _profile():
    return {"age": 30, "gender": "male", "height": 180, "weight": 80, "goal": "maintain", "training_frequency": 3}


def test_get_profile_before_save_is_null(profile_client):
    """A user who has not filled in a profile gets an explicit null rather than an error, which is the signal the dashboard uses to prompt them."""
    _login(profile_client)
    resp = profile_client.get("/profile")
    assert resp.status_code == 200
    assert resp.get_json()["profile"] is None


def test_save_then_get_profile_roundtrip(profile_client):
    """The WHOLE profile survives the round trip, field for field.

    Asserting only a couple of fields let a save path that silently dropped the others pass unnoticed.
    """
    _login(profile_client)
    assert profile_client.post("/profile", json=_profile()).status_code == 200
    # the WHOLE profile must survive the round-trip: asserting only age+goal let a mutation that
    # dropped height / weight / gender / training_frequency on save pass unnoticed.
    got = profile_client.get("/profile").get_json()["profile"]
    assert {k: got[k] for k in _profile()} == _profile()


def test_save_then_get_keeps_the_training_preferences(profile_client):
    """The two optional preferences reach the STORE, not just the validator.

    They were added after the original fields, so a save path that quietly dropped them would leave every unit test green — the validator still returns them, they just never get written. The read-back is the assertion that matters, not the echo from the save.
    """
    _login(profile_client)
    payload = {**_profile(), "equipment": ["barbell", "bands"], "split_preference": "upper_lower"}
    assert profile_client.post("/profile", json=payload).status_code == 200
    got = profile_client.get("/profile").get_json()["profile"]
    assert got["equipment"] == ["barbell", "bands"]
    assert got["split_preference"] == "upper_lower"


def test_save_invalid_profile_returns_400(profile_client):
    """Invalid data is refused at the route, so the validator is genuinely wired into the request path rather than merely existing."""
    _login(profile_client)
    bad = _profile()
    bad["age"] = "old"
    assert profile_client.post("/profile", json=bad).status_code == 400


def test_save_rejects_an_unknown_equipment_item(profile_client):
    """The preference rules are proven value by value as a unit; this proves the ROUTE is connected to them at all — something the original fields cannot demonstrate on their behalf."""
    _login(profile_client)
    bad = {**_profile(), "equipment": ["barbell", "treadmill"]}
    assert profile_client.post("/profile", json=bad).status_code == 400


def test_profile_is_per_user(profile_client):
    """A profile is scoped to its owner: another signed-in user sees their own absence of one, never somebody else's body measurements."""
    _login(profile_client, "alice")
    profile_client.post("/profile", json=_profile())
    profile_client.post("/logout")
    _login(profile_client, "bob")
    assert profile_client.get("/profile").get_json()["profile"] is None
