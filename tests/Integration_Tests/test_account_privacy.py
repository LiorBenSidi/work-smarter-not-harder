"""Account privacy & data — GDPR email-consent opt-in + data export. OWNER: Lior.

Consent defaults False (opt-in); toggling it persists and surfaces in /me + the export. Security email
(login OTP, password reset) is transactional and always sent regardless. The export returns everything
the app holds about the user as downloadable JSON — minus the password hash. Runs on the in-memory fakes.
"""
import json as _json

import pytest


@pytest.fixture
def full_client(make_client, fake_users, fake_profiles, fake_history, fake_forum, fake_messages,
                fake_notifications):
    return make_client(fake_users, profiles=fake_profiles, history=fake_history, forum=fake_forum,
                       messages=fake_messages, notifications=fake_notifications)


def _register_login(client, name="alice", pw="password123"):
    client.post("/register", json={"username": name, "password": pw, "email": f"{name}@ex.com"})
    r = client.post("/login", json={"username": name, "password": pw})
    assert r.status_code == 200
    return r.get_json()["username"]


# ---- email consent ----
def test_email_consent_defaults_false_and_toggles(client):
    _register_login(client)
    assert client.get("/me").get_json()["email_consent"] is False        # opt-in: off by default
    assert client.post("/account/email-consent", json={"consent": True}).status_code == 200
    assert client.get("/me").get_json()["email_consent"] is True          # persisted
    assert client.post("/account/email-consent", json={"consent": False}).status_code == 200
    assert client.get("/me").get_json()["email_consent"] is False


def test_email_consent_rejects_non_boolean(client):
    _register_login(client)
    assert client.post("/account/email-consent", json={"consent": "yes"}).status_code == 400
    assert client.post("/account/email-consent", json={}).status_code == 400


def test_email_consent_requires_auth(client):
    assert client.post("/account/email-consent", json={"consent": True}).status_code == 401


def test_security_email_is_sent_regardless_of_consent(make_otp_client, fake_users):
    # login OTP is transactional -> issued even though consent defaults False (the dev-surfaced code
    # proves the email path ran). Consent governs only NON-essential mail.
    c = make_otp_client(fake_users)
    c.post("/register", json={"username": "alice", "password": "password123", "email": "a@ex.com"})
    assert fake_users.get_email_consent("alice") is False                 # never opted in
    r = c.post("/login", json={"username": "alice", "password": "password123"})
    assert r.get_json()["status"] == "otp_required" and r.get_json().get("dev_otp")


# ---- data export ----
def test_export_returns_all_user_data_as_a_download(full_client, fake_profiles, fake_history, fake_forum,
                                                    fake_messages, fake_notifications):
    _register_login(full_client, "alice")
    fake_profiles.save("alice", {"age": 30, "goal": "maintain"})
    fake_history.add("alice", {"assessment": "Ready", "calories": 2000})
    fake_forum.create_post("alice", "My post", "body", False)
    bp = fake_forum.create_post("bob", "Bob's post", "b", False)
    fake_forum.add_comment(bp["id"], "alice", "my comment")
    fake_forum.vote(bp["id"], "alice", 1)
    fake_messages.send("alice", "bob", "hi bob")
    fake_notifications.add("alice", "dm", "bob", None, "Bob messaged you")
    full_client.post("/account/email-consent", json={"consent": True})

    r = full_client.get("/account/export")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    data = r.get_json()
    assert data["account"]["username"] == "alice" and data["account"]["email_consent"] is True
    assert data["profile"] == {"age": 30, "goal": "maintain"}
    assert len(data["history"]) == 1
    assert [p["title"] for p in data["forum"]["posts"]] == ["My post"]    # only alice's own post
    assert [c["body"] for c in data["forum"]["comments"]] == ["my comment"]
    assert len(data["forum"]["votes"]) == 1                               # her vote on bob's post
    assert len(data["messages"]) == 1 and len(data["notifications"]) == 1


def test_export_never_includes_the_password_hash(full_client):
    _register_login(full_client, "alice")
    data = full_client.get("/account/export").get_json()
    assert "password_hash" not in data["account"]
    assert "password_hash" not in _json.dumps(data)                       # nowhere in the whole blob


def test_export_requires_auth(full_client):
    assert full_client.get("/account/export").status_code == 401
