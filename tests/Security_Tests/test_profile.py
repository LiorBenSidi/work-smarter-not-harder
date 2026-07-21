"""Security tests for F2 profile — gated + injection-safe + graceful degradation. OWNER: Lior."""


def _login(c):
    c.post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    c.post("/login", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})


def _profile():
    return {"age": 30, "gender": "male", "height": 180, "weight": 80, "goal": "maintain", "training_frequency": 3}


# (GET/POST /profile auth-gating AND the `{"$gt": ...}` injection wall are covered by Negative_Tests —
#  the route matrix for the gate, and test_profile_rejects_each_bad_field (which injects the same object
#  into a field, via the same field-agnostic type check) for the injection. Only the 503-degradation
#  test below is unique to this file.)


class _BrokenProfiles:
    def get(self, username):
        raise RuntimeError("store down")

    def save(self, username, profile):
        raise RuntimeError("store down")


def test_profile_degrades_to_503_when_store_fails(make_client, fake_users):
    c = make_client(fake_users, _BrokenProfiles())
    c.post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    c.post("/login", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    assert c.post("/profile", json=_profile()).status_code == 503
