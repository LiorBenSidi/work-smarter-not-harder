"""Web-edge hardening tests (F1 security pass). OWNER: Lior.

Session-cookie flags (HttpOnly / SameSite always on, Secure env-gated), a request-body size cap
(413 before parsing), and the ephemeral-SECRET_KEY dev/test fallback — production sets a real
SECRET_KEY (compose enforces it via ${SECRET_KEY:?}).
"""
import sys


def _register_then_login(client):
    client.post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    return client.post("/login", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})


def test_session_cookie_secure_is_wired_to_its_environment_variable(monkeypatch, web_app_module):
    """The Secure flag on the session cookie is driven by SESSION_COOKIE_SECURE in the environment, and that wiring is what makes an HTTPS deploy actually set it.

    Its sibling below proves Flask honours the flag once it is True — but that test assigns the value
    itself, so it can never see the WIRING break. Measured before adding this: replacing the env lookup
    in web/config.py with a literal `False` left the whole suite green (1082 passed), meaning production
    could ship session cookies with no Secure attribute and nothing would fail.

    The value is read once at import time, so the module is reloaded under each environment rather than
    patched after the fact — patching the class attribute would test the patch, not the wiring.
    """
    import importlib.util

    def config_under(value):
        """Load a FRESH copy of web/config.py with the env var set, under a throwaway module name.

        A fresh load (rather than importlib.reload) keeps the real `config` module untouched for every
        other test in the session, and the app's own module is loaded by path, so it has no spec to
        reload from anyway.
        """
        monkeypatch.setenv("SESSION_COOKIE_SECURE", value)
        spec = importlib.util.spec_from_file_location("config_env_probe", sys.modules["config"].__file__)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.Config.SESSION_COOKIE_SECURE

    assert config_under("1") is True, "SESSION_COOKIE_SECURE=1 must switch the session cookie's Secure flag on"
    assert config_under("0") is False, "the flag must follow the environment, not be hard-coded"


def test_session_cookie_is_httponly_and_samesite_lax(client):
    """The session cookie is unreadable from JavaScript (HttpOnly) and is not attached to cross-site requests (SameSite), so an XSS or a forged form cannot lift or ride the session."""
    cookie = _register_then_login(client).headers.get("Set-Cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie


def test_session_cookie_secure_attribute_follows_config(web_app_module, fake_users):
    """On an HTTPS deploy the session cookie carries Secure, so it is never sent over a plain-HTTP request where it could be captured in transit."""
    app = web_app_module.create_app(users=fake_users)
    app.config.update(SECRET_KEY="x-test", TESTING=True, SESSION_COOKIE_SECURE=True)
    c = app.test_client()
    c.get("/health")  # issue the csrf cookie (double-submit)
    cc = c.get_cookie("csrf_token")
    headers = {"X-CSRF-Token": cc.value if cc else ""}
    c.post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"}, headers=headers)
    login = c.post("/login", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"}, headers=headers)
    session_cookie = next((ck for ck in login.headers.getlist("Set-Cookie") if ck.startswith("session=")), "")
    assert "Secure" in session_cookie


def test_oversized_request_body_is_rejected_413(client):
    """An over-large body is refused at the edge with a 413 rather than being parsed, so a single request cannot exhaust memory on the way in."""
    big = "a" * (64 * 1024 + 1)  # one byte over the 64 KB cap
    resp = client.post("/register", data=big, content_type="application/json")
    assert resp.status_code == 413


def test_generates_ephemeral_secret_key_when_unset(web_app_module):
    """With no SECRET_KEY configured the app boots on a generated one of real length — never an empty key, which would make every session cookie trivially forgeable."""
    base = sys.modules["config"].Config
    cfg = type("NoSecret", (base,), {"SECRET_KEY": ""})
    app = web_app_module.create_app(config=cfg)
    assert app.config["SECRET_KEY"]
    assert len(app.config["SECRET_KEY"]) >= 32
