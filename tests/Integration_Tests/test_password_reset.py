"""Integration: register requires a valid email + the forgot/reset-password flow. OWNER: Lior.

The reset email is intercepted (the route's ``send_email_async`` is monkeypatched) to read the emitted
link without a real mail server. Reset flows use a signed, single-use, time-limited token (itsdangerous).
The route dispatches the send via ``send_email_async`` so a live SMTP send never blocks the response —
which is what keeps the registered/unregistered branches timing-identical (AUTH-H1).
"""
import re


def _register(client, username="alice", password="s3cretpw!", email="alice@example.com"):
    return client.post("/register", json={"username": username, "password": password, "email": email})


def _capture_reset(client, auth_module, monkeypatch, email="alice@example.com"):
    box = {}
    monkeypatch.setattr(auth_module, "send_email_async",
                        lambda cfg, to, subj, body, **kw: box.update(to=to, body=body) or True)
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
    monkeypatch.setattr(auth_module, "send_email_async", lambda *a, **k: True)   # don't spawn a real send thread
    _register(client)
    known = client.post("/forgot-password", json={"email": "alice@example.com"})
    unknown = client.post("/forgot-password", json={"email": "ghost@nowhere.co"})
    assert known.status_code == unknown.status_code == 200
    assert known.get_json() == unknown.get_json()          # identical body -> no account enumeration


def test_forgot_password_dispatches_the_send_asynchronously(client, auth_module, monkeypatch):
    # AUTH-H1: the registered branch must emit the reset email via the async wrapper, so a live SMTP send
    # never blocks the response and its latency can't be told apart from the unregistered (no-send) branch.
    seen = []
    monkeypatch.setattr(auth_module, "send_email_async", lambda cfg, to, *a, **k: seen.append(to) or True)
    _register(client)
    client.post("/forgot-password", json={"email": "alice@example.com"})
    client.post("/forgot-password", json={"email": "ghost@nowhere.co"})   # unknown -> no send
    assert seen == ["alice@example.com"], "registered forgot-password must dispatch via send_email_async; unknown must not send"


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


def test_forgot_password_fails_closed_in_production_posture(client):
    # Prod posture (SESSION_COOKIE_SECURE on) + no SMTP: the reset link must NOT be surfaced, even for a
    # registered email — so a mis-deploy without SMTP can't leak a reset token to an unauthenticated caller.
    client.raw.application.config["SESSION_COOKIE_SECURE"] = True
    _register(client)
    resp = client.post("/forgot-password", json={"email": "alice@example.com"}).get_json()
    assert "dev_reset_link" not in resp


def test_deeply_nested_json_is_400_not_500(client):
    # An over-nested body overflows the JSON parser (RecursionError). That's malformed input -> 400, not a 500.
    client.raw.application.config["PROPAGATE_EXCEPTIONS"] = False   # let the app error handler run, as in prod
    depth = 6000
    resp = client.post("/register", data="[" * depth + "]" * depth, content_type="application/json")
    assert resp.status_code == 400
