"""Integration tests for F8 history — GET /history reads the user's past analyses. OWNER: Lior."""


def _login(c, username="alice"):
    c.post("/register", json={"username": username, "password": "s3cretpw!"})
    c.post("/login", json={"username": username, "password": "s3cretpw!"})


def _entry(state="Ready"):
    return {"assessment": state, "recommendations": ["rest"], "calories": 2500, "timestamp": "2026-06-28T10:00:00Z"}


def test_history_empty_when_none_saved(history_client):
    _login(history_client)
    resp = history_client.get("/history")
    assert resp.status_code == 200
    assert resp.get_json()["history"] == []


def test_history_returns_the_users_entries(history_client, fake_history):
    fake_history.add("alice", _entry("Ready"))
    fake_history.add("alice", _entry("Recovery-Needed"))
    _login(history_client, "alice")
    entries = history_client.get("/history").get_json()["history"]
    assert len(entries) == 2
    assert entries[0]["assessment"] == "Ready"


def test_history_is_per_user(history_client, fake_history):
    fake_history.add("alice", _entry())
    _login(history_client, "bob")  # bob has no history of his own
    assert history_client.get("/history").get_json()["history"] == []
