"""Security tests for the gated DEV email-mock override (`X-Debug-Email: mock`). OWNER: Lior.

The override lets a developer pull the auth code back in the response instead of emailing it — a
deliberate, testing-only hole for exercising signup/login/reset on a live-SMTP deploy without an inbox.
It MUST be fail-closed: **inert unless the SERVER opted in** (`AUTH_DEBUG_EMAIL`). The client header
alone can NEVER surface a code — otherwise a public deploy would be an account-takeover machine
(forgot-password would hand the reset link to anyone who merely knows a registered email address).

These tests pin that contract: flag-off + header → no leak; flag-on + header → code surfaced and the
log backend forced (no real send); flag-on + no header → still emails; and `TESTING` hard-disables it.
`send_email` is patched so no test ever touches the network — the assertions are on the route's
returned body + how `send_email` was called, i.e. behaviour, not mechanism.
"""
from unittest.mock import patch


def _register(client, username="alice", password="s3cretpw!"):
    return client.post("/register", json={"username": username, "password": password,
                                          "email": f"{username}@example.com"})


def _login(client, headers=None):
    return client.post("/login", json={"username": "alice", "password": "s3cretpw!"}, headers=headers or {})


def test_header_alone_does_not_leak_code_when_flag_off(make_otp_client, fake_users, auth_module):
    # SMTP configured, AUTH_DEBUG_EMAIL NOT set (the default). The X-Debug-Email header must be INERT:
    # the code goes out by email and is never returned. This is the property that keeps prod safe.
    client = make_otp_client(fake_users, SMTP_HOST="smtp.example.com")
    with patch.object(auth_module, "send_email", return_value=True) as sent:
        _register(client)
        resp = _login(client, headers={"X-Debug-Email": "mock"})
    assert resp.status_code == 200
    assert "dev_otp" not in resp.get_json()                    # code did NOT leak to the client
    assert sent.call_args.kwargs.get("force_mock") is False    # real-email path, log backend not forced


def test_flag_and_header_together_return_code_over_smtp(make_otp_client, fake_users, auth_module):
    # Server opted in (AUTH_DEBUG_EMAIL) AND the client asked (header): the code comes back on-screen
    # even though SMTP is configured, and send_email is told to use the log backend (nothing is sent).
    client = make_otp_client(fake_users, SMTP_HOST="smtp.example.com", AUTH_DEBUG_EMAIL=True)
    with patch.object(auth_module, "send_email", return_value=True) as sent:
        _register(client)
        resp = _login(client, headers={"X-Debug-Email": "mock"})
    assert resp.status_code == 200
    assert resp.get_json().get("dev_otp")                      # code surfaced for the dev
    assert sent.call_args.kwargs.get("force_mock") is True     # log backend forced -> no real send


def test_flag_on_but_no_header_still_emails(make_otp_client, fake_users, auth_module):
    # Opt-in is PER REQUEST: with the flag on but no header, a normal login takes the real email path.
    client = make_otp_client(fake_users, SMTP_HOST="smtp.example.com", AUTH_DEBUG_EMAIL=True)
    with patch.object(auth_module, "send_email", return_value=True) as sent:
        _register(client)
        resp = _login(client)                                  # no X-Debug-Email header
    assert "dev_otp" not in resp.get_json()
    assert sent.call_args.kwargs.get("force_mock") is False


def test_forgot_password_reset_link_gated_off_by_default(make_otp_client, fake_users, auth_module):
    # The critical vector: forgot-password only needs the email. With the flag OFF the reset link must
    # NEVER come back — even with the mock header — or anyone knowing an email could reset the password.
    client = make_otp_client(fake_users, SMTP_HOST="smtp.example.com")   # flag off (default)
    with patch.object(auth_module, "send_email", return_value=True):
        _register(client)
        resp = client.post("/forgot-password", json={"email": "alice@example.com"},
                           headers={"X-Debug-Email": "mock"})
    assert resp.status_code == 200
    assert "dev_reset_link" not in resp.get_json()             # reset token did NOT leak


def test_forgot_password_reset_link_surfaced_when_opted_in(make_otp_client, fake_users, auth_module):
    # With the server flag on + the header, the same flow may surface the link (the developer's inbox-free
    # reset path). This is the deliberate behaviour the flag guards.
    client = make_otp_client(fake_users, SMTP_HOST="smtp.example.com", AUTH_DEBUG_EMAIL=True)
    with patch.object(auth_module, "send_email", return_value=True):
        _register(client)
        resp = client.post("/forgot-password", json={"email": "alice@example.com"},
                           headers={"X-Debug-Email": "mock"})
    assert resp.status_code == 200
    assert resp.get_json().get("dev_reset_link")


def test_predicate_gate_matrix(web_app_module, fake_users, auth_module):
    # Directly pin _debug_email_mock()'s truth table — the single choke point every auth flow routes
    # through. flag off -> False; flag on + header -> True; flag on + no header -> False; TESTING wins.
    app = web_app_module.create_app(users=fake_users)
    app.config.update(SECRET_KEY="k", TESTING=False, AUTH_DEBUG_EMAIL=False)
    with app.test_request_context(headers={"X-Debug-Email": "mock"}):
        assert auth_module._debug_email_mock() is False        # flag off -> header inert
    app.config.update(AUTH_DEBUG_EMAIL=True)
    with app.test_request_context(headers={"X-Debug-Email": "mock"}):
        assert auth_module._debug_email_mock() is True         # opted in + asked
    with app.test_request_context():                           # opted in, but no header
        assert auth_module._debug_email_mock() is False
    with app.test_request_context(headers={"X-Debug-Email": "LIVE"}):
        assert auth_module._debug_email_mock() is False        # any non-"mock" value -> off
    app.config.update(TESTING=True)                            # TESTING hard-disables regardless of flag
    with app.test_request_context(headers={"X-Debug-Email": "mock"}):
        assert auth_module._debug_email_mock() is False


def test_auth_config_advertises_toggle_only_when_enabled(make_otp_client, fake_users):
    # The panel reveals the Live/Mock switch iff /auth/config says so — true only when the flag is on AND
    # not under TESTING (so the switch never shows on a deploy that can't honour it).
    off = make_otp_client(fake_users)                          # AUTH_DEBUG_EMAIL unset
    assert off.get("/auth/config").get_json()["email_debug_toggle"] is False
    on = make_otp_client(fake_users, AUTH_DEBUG_EMAIL=True)
    assert on.get("/auth/config").get_json()["email_debug_toggle"] is True
    testing = make_otp_client(fake_users, AUTH_DEBUG_EMAIL=True, TESTING=True)
    assert testing.get("/auth/config").get_json()["email_debug_toggle"] is False
