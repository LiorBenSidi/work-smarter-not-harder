"""Security tests for F8 history — gated + graceful store failure. OWNER: Lior."""


class _BrokenHistory:
    def list(self, username):
        raise RuntimeError("store down")

    def add(self, username, entry):
        raise RuntimeError("store down")


# (GET /history auth-gating is in the Negative_Tests 13-route matrix. The 503-degradation test
#  below stays: this file owns it, and its only other twin is bundled inside a teammate's test.)


def test_history_degrades_to_503_when_store_fails(make_client, fake_users):
    c = make_client(fake_users, history=_BrokenHistory())
    c.post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    c.post("/login", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    assert c.get("/history").status_code == 503
