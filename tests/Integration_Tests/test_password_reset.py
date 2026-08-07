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
    """An account cannot be created without a usable email address, because that address is the only route back in if the password is ever lost."""
    assert client.post("/register", json={"username": "alice", "password": "s3cretpw!"}).status_code == 400
    assert client.post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "nope"}).status_code == 400
    assert _register(client).status_code == 201


def test_forgot_password_never_enumerates_accounts(client, auth_module, monkeypatch):
    """With real email configured, a known and an unknown address get byte-identical answers, so the endpoint cannot be used to discover who has an account.

    The development mode that shows the link on screen necessarily differs, which is why the property is asserted with a relay configured.
    """
    client.raw.application.config["SMTP_HOST"] = "relay.test"
    monkeypatch.setattr(auth_module, "send_email_async", lambda *a, **k: True)   # don't spawn a real send thread
    _register(client)
    known = client.post("/forgot-password", json={"email": "alice@example.com"})
    unknown = client.post("/forgot-password", json={"email": "ghost@nowhere.co"})
    assert known.status_code == unknown.status_code == 200
    assert known.get_json() == unknown.get_json()          # identical body -> no account enumeration


def test_forgot_password_dispatches_the_send_asynchronously(client, auth_module, monkeypatch):
    """The registered branch hands the email to the background sender, so a slow relay never blocks the response — otherwise the reply's LATENCY tells an attacker which addresses are registered, even when the body does not."""
    seen = []
    monkeypatch.setattr(auth_module, "send_email_async", lambda cfg, to, *a, **k: seen.append(to) or True)
    _register(client)
    client.post("/forgot-password", json={"email": "alice@example.com"})
    client.post("/forgot-password", json={"email": "ghost@nowhere.co"})   # unknown -> no send
    assert seen == ["alice@example.com"], "registered forgot-password must dispatch via send_email_async; unknown must not send"


def test_forgot_password_dev_surfaces_the_link_without_smtp(client):
    """Without a relay, a registered address gets the link on screen so the flow is usable with no inbox — and an unregistered one still gets nothing."""
    _register(client)
    known = client.post("/forgot-password", json={"email": "alice@example.com"}).get_json()
    unknown = client.post("/forgot-password", json={"email": "ghost@nowhere.co"}).get_json()
    assert "reset_token=" in known.get("dev_reset_link", "")
    assert "dev_reset_link" not in unknown


def test_reset_with_a_valid_token_changes_the_password(client, auth_module, monkeypatch):
    """The whole point of the flow: a valid link genuinely changes the password, the old one stops working, and the new one does."""
    _register(client)
    box = _capture_reset(client, auth_module, monkeypatch)
    assert box["to"] == "alice@example.com"
    token = re.search(r"reset_token=([\w.\-]+)", box["body"]).group(1)
    assert client.post("/reset-password", json={"token": token, "password": "newpass123"}).status_code == 200
    assert client.post("/login", json={"username": "alice", "password": "s3cretpw!"}).status_code == 401   # old pw dead
    assert client.post("/login", json={"username": "alice", "password": "newpass123"}).status_code == 200  # new pw works


def test_reset_token_is_single_use(client, auth_module, monkeypatch):
    """Replaying the same link after the password changed is refused, so an old email sitting in an inbox cannot be used a second time to seize the account."""
    _register(client)
    token = re.search(r"reset_token=([\w.\-]+)",
                      _capture_reset(client, auth_module, monkeypatch)["body"]).group(1)
    assert client.post("/reset-password", json={"token": token, "password": "newpass123"}).status_code == 200
    # replaying the same link after the password changed is rejected (the token embeds the old hash prefix)
    assert client.post("/reset-password", json={"token": token, "password": "other12345"}).status_code == 400


def test_reset_rejects_a_garbage_token(client):
    """An invented token is refused, so the reset endpoint cannot be driven by guessing."""
    assert client.post("/reset-password", json={"token": "not-a-real-token", "password": "newpass123"}).status_code == 400


def test_forgot_password_fails_closed_in_production_posture(client):
    """In a production posture with no relay configured, the link is NOT surfaced even for a registered address.

    Without this, a mis-deploy that forgot the mail settings would hand a working reset token to any anonymous caller who knows an email address.
    """
    client.raw.application.config["SESSION_COOKIE_SECURE"] = True
    _register(client)
    resp = client.post("/forgot-password", json={"email": "alice@example.com"}).get_json()
    assert "dev_reset_link" not in resp


def test_deeply_nested_json_is_400_not_500(client):
    """A deeply nested body overflows the JSON parser, and that is malformed input from the caller — a 400 — not a server fault that should surface as a 500 and page whoever is on call."""
    client.raw.application.config["PROPAGATE_EXCEPTIONS"] = False   # let the app error handler run, as in prod
    depth = 6000
    resp = client.post("/register", data="[" * depth + "]" * depth, content_type="application/json")
    assert resp.status_code == 400


def test_reset_token_window_is_ten_minutes():
    """The link expires on a fixed, single-sourced window, so the enforcement and the wording in the email can never drift apart and promise the user a different lifetime than the server honours."""
    from config import Config
    assert Config.RESET_TOKEN_MAX_AGE == 600


def test_reset_link_expires_after_its_max_age(client, auth_module, monkeypatch):
    """A stale reset email is refused because the token carries its issue time — and, critically, the password is left unchanged, so a rejected reset never half-applies."""
    _register(client)
    token = re.search(r"reset_token=([\w.\-]+)", _capture_reset(client, auth_module, monkeypatch)["body"]).group(1)
    monkeypatch.setitem(client.raw.application.config, "RESET_TOKEN_MAX_AGE", -1)   # the just-issued token is now "too old"
    r = client.post("/reset-password", json={"token": token, "password": "newpass123"})
    assert r.status_code == 400 and "expired" in (r.get_json() or {}).get("error", "")
    # the password did NOT change (still the original)
    assert client.post("/login", json={"username": "alice", "password": "s3cretpw!"}).status_code == 200
