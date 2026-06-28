"""Web-edge hardening tests (F1 security pass). OWNER: Lior.

Session-cookie flags (HttpOnly / SameSite always on, Secure env-gated), a request-body size cap
(413 before parsing), and the ephemeral-SECRET_KEY dev/test fallback — production sets a real
SECRET_KEY (compose enforces it via ${SECRET_KEY:?}).
"""
import sys


def _register_then_login(client):
    client.post("/register", json={"username": "alice", "password": "s3cretpw!"})
    return client.post("/login", json={"username": "alice", "password": "s3cretpw!"})


def test_session_cookie_is_httponly_and_samesite_lax(client):
    cookie = _register_then_login(client).headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_session_cookie_secure_attribute_follows_config(web_app_module, fake_users):
    app = web_app_module.create_app(users=fake_users)
    app.config.update(SECRET_KEY="x-test", TESTING=True, SESSION_COOKIE_SECURE=True)
    c = app.test_client()
    c.get("/health")  # issue the csrf cookie (double-submit)
    cc = c.get_cookie("csrf_token")
    headers = {"X-CSRF-Token": cc.value if cc else ""}
    c.post("/register", json={"username": "alice", "password": "s3cretpw!"}, headers=headers)
    login = c.post("/login", json={"username": "alice", "password": "s3cretpw!"}, headers=headers)
    session_cookie = next((ck for ck in login.headers.getlist("Set-Cookie") if ck.startswith("session=")), "")
    assert "Secure" in session_cookie


def test_oversized_request_body_is_rejected_413(client):
    big = "a" * (64 * 1024 + 1)  # one byte over the 64 KB cap
    resp = client.post("/register", data=big, content_type="application/json")
    assert resp.status_code == 413


def test_generates_ephemeral_secret_key_when_unset(web_app_module):
    # with no SECRET_KEY configured, the app must still boot on a generated key (never an empty one)
    base = sys.modules["config"].Config
    cfg = type("NoSecret", (base,), {"SECRET_KEY": ""})
    app = web_app_module.create_app(config=cfg)
    assert app.config["SECRET_KEY"]
    assert len(app.config["SECRET_KEY"]) >= 32
