"""The global JSON error handlers (app.py). The API contract is JSON everywhere, so a raised HTTP error
(stray path 404, wrong-method 405, oversize 413, flask-limiter 429) and any genuinely-unexpected exception
must return the same {"error": ...} shape the hand-written errors use — never Werkzeug's HTML page (which
the SPA's fetch layer can't parse) and never a traceback. OWNER: Lior.
"""


def test_unknown_path_returns_json_404_not_html(client):
    r = client.get("/no/such/route")
    assert r.status_code == 404
    assert r.is_json, "a 404 must be JSON so the SPA can read it, not an HTML page"
    assert r.get_json()["error"] == "not found"


def test_wrong_method_returns_json_405(client):
    r = client.get("/login")                                # /login is POST-only
    assert r.status_code == 405
    assert r.is_json and r.get_json()["error"]              # a friendly JSON reason, not HTML


def test_http_error_body_never_leaks_werkzeug_html(client):
    # belt-and-suspenders: the body is pure JSON, with no HTML traceback/boilerplate.
    body = client.get("/no/such/route").get_data(as_text=True)
    assert "<!doctype" not in body.lower() and "<html" not in body.lower()


def test_unexpected_exception_is_a_generic_json_500(web_app_module, fake_users):
    # A route that raises an unwrapped, unexpected error (e.g. a disk/store failure) must degrade to a
    # generic JSON 500 — no traceback, no internal detail — and the real error is logged server-side.
    app = web_app_module.create_app(users=fake_users)
    app.config.update(SECRET_KEY="test-secret-key", TESTING=True, RATELIMIT_ENABLED=False)

    @app.route("/__boom__")
    def _boom():
        raise RuntimeError("disk on fire: /var/secret/path")   # an internal detail that must NOT surface

    r = app.test_client().get("/__boom__")
    assert r.status_code == 500
    assert r.is_json, "an unexpected 500 must still be JSON, not an HTML error page"
    msg = r.get_json()["error"]
    assert msg and "disk on fire" not in msg and "/var/secret" not in msg   # internals stay server-side


def test_known_json_errors_are_unchanged(client):
    # The new catch-alls must not disturb the routes that already return curated JSON errors:
    # an unauthenticated API call is still a clean 401 JSON (not swallowed into a 500).
    r = client.get("/dashboard")
    assert r.status_code == 401
    assert r.is_json and r.get_json()["error"]
