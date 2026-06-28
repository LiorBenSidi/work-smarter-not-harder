"""Security tests for CSRF protection (double-submit cookie). OWNER: Lior.

`client` is the CSRF-aware wrapper (auto-sends the matching header); `client.raw` is the unwrapped
Flask test client used to simulate a forged request that lacks / mismatches the token.
"""


def _creds():
    return {"username": "alice", "password": "s3cretpw!"}


def test_unsafe_request_without_token_is_rejected_403(client):
    resp = client.raw.post("/register", json=_creds())  # no X-CSRF-Token header
    assert resp.status_code == 403


def test_mismatched_token_is_rejected_403(client):
    resp = client.raw.post("/register", json=_creds(), headers={"X-CSRF-Token": "not-the-real-token"})
    assert resp.status_code == 403


def test_valid_token_is_accepted(client):
    assert client.post("/register", json=_creds()).status_code == 201  # wrapper sends the matching token


def test_get_requests_need_no_token(client):
    assert client.raw.get("/health").status_code == 200


def _csrf_set_cookie_header(web_app_module, fake_users, *, secure):
    app = web_app_module.create_app(users=fake_users)
    app.config.update(SECRET_KEY="test-secret-key", TESTING=True, SESSION_COOKIE_SECURE=secure)
    resp = app.test_client().get("/health")  # first contact issues the csrf cookie
    for header in resp.headers.getlist("Set-Cookie"):
        if header.startswith("csrf_token="):
            return header
    raise AssertionError("no csrf_token cookie was issued")


def test_csrf_cookie_is_secure_in_production(web_app_module, fake_users):
    # production HTTPS (SESSION_COOKIE_SECURE on) -> the token cookie must carry Secure (no downgrade leak)
    assert "Secure" in _csrf_set_cookie_header(web_app_module, fake_users, secure=True)


def test_csrf_cookie_is_not_secure_over_dev_http(web_app_module, fake_users):
    # dev default (off) -> no Secure, so the token still works over the local HTTP server
    assert "Secure" not in _csrf_set_cookie_header(web_app_module, fake_users, secure=False)
