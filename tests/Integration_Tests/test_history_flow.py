"""Integration tests for F8 history — GET /history reads the user's past analyses. OWNER: Lior."""


def _login(c, username="alice"):
    c.post("/register", json={"username": username, "password": "s3cretpw!", "email": f"{username}@example.com"})
    c.post("/login", json={"username": username, "password": "s3cretpw!"})


def _entry(state="Ready", ts="2026-06-28T10:00:00Z"):
    # ts is per-day: history is now one row per UTC day (a second same-day check-in replaces the first), so a
    # multi-entry test must use DISTINCT days to represent distinct check-ins.
    return {"assessment": state, "recommendations": ["rest"], "calories": 2500, "timestamp": ts}


def test_history_empty_when_none_saved(history_client):
    _login(history_client)
    resp = history_client.get("/history")
    assert resp.status_code == 200
    assert resp.get_json()["history"] == []


def test_history_returns_the_users_entries(history_client, fake_history):
    fake_history.add("alice", _entry("Ready", "2026-06-27T10:00:00Z"))
    fake_history.add("alice", _entry("Recovery-Needed", "2026-06-28T10:00:00Z"))   # distinct day -> both kept
    _login(history_client, "alice")
    entries = history_client.get("/history").get_json()["history"]
    assert len(entries) == 2
    assert entries[0]["assessment"] == "Ready"


def test_history_is_per_user(history_client, fake_history):
    fake_history.add("alice", _entry())
    _login(history_client, "bob")  # bob has no history of his own
    assert history_client.get("/history").get_json()["history"] == []


def test_history_view_is_bounded_to_the_newest_cap(history_client, fake_history):
    # #331: however long a user's daily log grows, GET /history returns at most HISTORY_VIEW_CAP entries — the
    # NEWEST ones, oldest-first — so one request can't pull an unbounded history. (The GDPR export is unbounded
    # by design; it calls .list() with no cap.)
    from datetime import date, timedelta

    from services.db import HISTORY_VIEW_CAP
    base, n = date(2023, 1, 1), HISTORY_VIEW_CAP + 5
    for i in range(n):
        fake_history.add("alice", _entry("Ready", f"{(base + timedelta(days=i)).isoformat()}T10:00:00Z"))
    _login(history_client, "alice")
    entries = history_client.get("/history").get_json()["history"]
    assert len(entries) == HISTORY_VIEW_CAP                                              # capped to the newest N
    assert entries[0]["timestamp"].startswith((base + timedelta(days=5)).isoformat())    # oldest kept = day #5
    assert entries[-1]["timestamp"].startswith((base + timedelta(days=n - 1)).isoformat())  # newest = the last day
