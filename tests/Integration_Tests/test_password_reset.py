"""Integration: register requires a valid email + the forgot/reset-password flow. OWNER: Lior.

The reset email is intercepted (the route's ``send_email`` is monkeypatched) to read the emitted link
without a real mail server. Reset flows use a signed, single-use, time-limited token (itsdangerous).
"""
import re


def _register(client, username="alice", password="s3cretpw!", email="alice@example.com"):
    return client.post("/register", json={"username": username, "password": password, "email": email})


def _capture_reset(client, auth_module, monkeypatch, email="alice@example.com"):
    box = {}
    monkeypatch.setattr(auth_module, "send_email",
                        lambda cfg, to, subj, body: box.update(to=to, body=body) or True)
    client.post("/forgot-password", json={"email": email})
    return box


def test_register_requires_a_valid_email(client):
    assert client.post("/register", json={"username": "alice", "password": "s3cretpw!"}).status_code == 400
    assert client.post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "nope"}).status_code == 400
    assert _register(client).status_code == 201


def test_forgot_password_never_enumerates_accounts(client, auth_module, monkeypatch):
    # No-enumeration is a LIVE (SMTP) property: with real email configured, the link leaves ONLY by email, so
    # known vs unknown are byte-identical. (In dev/log mode the link is dev-surfaced on-screen — which
    # necessarily differs for a registered email — a local-only convenience, tested separately below.)
    client.raw.application.config["SMTP_HOST"] = "relay.test"
    monkeypatch.setattr(auth_module, "send_email", lambda *a, **k: True)   # don't actually connect out
    _register(client)
    known = client.post("/forgot-password", json={"email": "alice@example.com"})
    unknown = client.post("/forgot-password", json={"email": "ghost@nowhere.co"})
    assert known.status_code == unknown.status_code == 200
    assert known.get_json() == unknown.get_json()          # identical body -> no account enumeration


def test_forgot_password_dev_surfaces_the_link_without_smtp(client):
    # Dev/log mode (no SMTP_HOST): a registered email gets the reset link surfaced in the response so the flow
    # is testable with no inbox; an unregistered email does NOT (and none of this is exposed once SMTP is set).
    _register(client)
    known = client.post("/forgot-password", json={"email": "alice@example.com"}).get_json()
    unknown = client.post("/forgot-password", json={"email": "ghost@nowhere.co"}).get_json()
    assert "reset_token=" in known.get("dev_reset_link", "")
    assert "dev_reset_link" not in unknown


def test_reset_with_a_valid_token_changes_the_password(client, auth_module, monkeypatch):
    _register(client)
    box = _capture_reset(client, auth_module, monkeypatch)
    assert box["to"] == "alice@example.com"
    token = re.search(r"reset_token=([\w.\-]+)", box["body"]).group(1)
    assert client.post("/reset-password", json={"token": token, "password": "newpass123"}).status_code == 200
    assert client.post("/login", json={"username": "alice", "password": "s3cretpw!"}).status_code == 401   # old pw dead
    assert client.post("/login", json={"username": "alice", "password": "newpass123"}).status_code == 200  # new pw works


def test_reset_token_is_single_use(client, auth_module, monkeypatch):
    _register(client)
    token = re.search(r"reset_token=([\w.\-]+)",
                      _capture_reset(client, auth_module, monkeypatch)["body"]).group(1)
    assert client.post("/reset-password", json={"token": token, "password": "newpass123"}).status_code == 200
    # replaying the same link after the password changed is rejected (the token embeds the old hash prefix)
    assert client.post("/reset-password", json={"token": token, "password": "other12345"}).status_code == 400


def test_reset_rejects_a_garbage_token(client):
    assert client.post("/reset-password", json={"token": "not-a-real-token", "password": "newpass123"}).status_code == 400
