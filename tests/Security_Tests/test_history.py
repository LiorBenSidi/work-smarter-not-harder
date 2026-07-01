"""Security tests for F8 history — gated + graceful store failure. OWNER: Lior."""


class _BrokenHistory:
    def list(self, username):
        raise RuntimeError("store down")

    def add(self, username, entry):
        raise RuntimeError("store down")


def test_history_requires_login(history_client):
    assert history_client.get("/history").status_code == 401


def test_history_degrades_to_503_when_store_fails(make_client, fake_users):
    c = make_client(fake_users, history=_BrokenHistory())
    c.post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    c.post("/login", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    assert c.get("/history").status_code == 503
