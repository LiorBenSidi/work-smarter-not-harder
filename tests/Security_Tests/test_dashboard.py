"""Security tests for F7 dashboard — gated + graceful store failure. OWNER: Lior."""


class _BrokenProfiles:
    def get(self, username):
        raise RuntimeError("store down")

    def save(self, username, profile):
        raise RuntimeError("store down")


# (GET /dashboard auth-gating is in the Negative_Tests 13-route matrix. The broken-profile-store
#  503 test below stays — no other test drives /dashboard with that dependency failing.)


def test_dashboard_degrades_to_503_when_profile_store_fails(make_client, fake_users):
    c = make_client(fake_users, _BrokenProfiles())
    c.post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    c.post("/login", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    assert c.get("/dashboard").status_code == 503
