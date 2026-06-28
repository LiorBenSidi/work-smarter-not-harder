"""Security tests for F7 dashboard — gated + graceful store failure. OWNER: Lior."""


class _BrokenProfiles:
    def get(self, username):
        raise RuntimeError("store down")

    def save(self, username, profile):
        raise RuntimeError("store down")


def test_dashboard_requires_login(profile_client):
    assert profile_client.get("/dashboard").status_code == 401


def test_dashboard_degrades_to_503_when_profile_store_fails(make_client, fake_users):
    c = make_client(fake_users, _BrokenProfiles())
    c.post("/register", json={"username": "alice", "password": "s3cretpw!"})
    c.post("/login", json={"username": "alice", "password": "s3cretpw!"})
    assert c.get("/dashboard").status_code == 503
