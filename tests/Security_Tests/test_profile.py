"""Security tests for F2 profile — gated + injection-safe + graceful degradation. OWNER: Lior."""


def _login(c):
    c.post("/register", json={"username": "alice", "password": "s3cretpw!"})
    c.post("/login", json={"username": "alice", "password": "s3cretpw!"})


def _profile():
    return {"age": 30, "gender": "male", "height": 180, "weight": 80, "goal": "maintain", "training_frequency": 3}


def test_get_profile_requires_login(profile_client):
    assert profile_client.get("/profile").status_code == 401


def test_post_profile_requires_login(profile_client):
    assert profile_client.post("/profile", json=_profile()).status_code == 401


def test_injection_in_profile_field_rejected(profile_client):
    _login(profile_client)
    bad = _profile()
    bad["weight"] = {"$gt": 0}
    assert profile_client.post("/profile", json=bad).status_code == 400


class _BrokenProfiles:
    def get(self, username):
        raise RuntimeError("store down")

    def save(self, username, profile):
        raise RuntimeError("store down")


def test_profile_degrades_to_503_when_store_fails(make_client, fake_users):
    c = make_client(fake_users, _BrokenProfiles())
    c.post("/register", json={"username": "alice", "password": "s3cretpw!"})
    c.post("/login", json={"username": "alice", "password": "s3cretpw!"})
    assert c.post("/profile", json=_profile()).status_code == 503
