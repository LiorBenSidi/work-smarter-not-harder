"""Frontend shell test — GET / serves the single-page app with its API hooks. OWNER: Lior.

JS behaviour itself needs a browser (exercised by the running stack / system tests); this pins that
the page is served and wired to every endpoint, so a template break is caught in CI.
"""


def test_index_serves_html(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type


def test_index_has_the_main_sections(client):
    html = client.get("/").get_data(as_text=True).lower()
    for hook in ["login", "register", "profile", "dashboard", "history", "logout", "forum"]:
        assert hook in html


def test_index_references_every_api_endpoint(client):
    html = client.get("/").get_data(as_text=True)
    for endpoint in ["/register", "/login", "/logout", "/me", "/profile", "/dashboard", "/history", "/forum/posts"]:
        assert endpoint in html


def test_dashboard_escapes_ai_provided_fields(client):
    # The AI container's `state` + each recommendation are attacker-influenced (a compromised/buggy
    # ai service could return HTML). They must be escaped before innerHTML, like the forum already is.
    html = client.get("/").get_data(as_text=True)
    assert "escapeHtml(d.readiness.state" in html
    assert "escapeHtml(x)" in html  # each recommendation in the recs.map
    assert "escapeHtml(d.calories" in html


def test_history_escapes_entry_fields(client):
    # History rows carry AI-generated assessment text + a timestamp -> escape before innerHTML.
    html = client.get("/").get_data(as_text=True)
    assert "escapeHtml(it.assessment" in html
    assert "escapeHtml(it.timestamp" in html
    assert "escapeHtml(it.calories" in html


def test_forum_list_escapes_post_id(client):
    # post id is interpolated into a data-id HTML attribute; a store-supplied id must be escaped too.
    html = client.get("/").get_data(as_text=True)
    assert "escapeHtml(p.id)" in html


def test_ui_polish_present(client):
    # UX guards: responsive collapse, double-submit guard, and aria-live flash regions.
    html = client.get("/").get_data(as_text=True)
    assert "@media (max-width:" in html            # profile grid collapses on mobile
    assert "btn.disabled = true" in html           # submit disabled while a request is in flight
    assert 'aria-live="polite"' in html            # flash messages announced to assistive tech


def test_served_html_has_no_unrendered_template_placeholders(client):
    # guard against the raw `{{ ... }}` bug: the served shell must carry no template placeholders.
    html = client.get("/").get_data(as_text=True)
    assert "{{" not in html and "}}" not in html


def test_forum_owner_edit_delete_wired(client):
    # the detail view exposes edit/delete for the author's own posts, hitting PATCH/DELETE.
    html = client.get("/").get_data(as_text=True)
    assert "editPost()" in html and "deletePost()" in html
    assert 'method: "PATCH"' in html and 'method: "DELETE"' in html
    assert "p.mine" in html  # buttons only on own posts (server-computed per-viewer flag; preserves anonymity)


def test_async_renderers_guard_against_stale_session_paint(client):
    # regression for the cross-user data-bleed race: every session-scoped async renderer snapshots
    # currentUser before its await and bails (via sessionChanged) if the session changed before it
    # paints — else a slow response from user A overwrites user B's view after a fast logout->login.
    html = client.get("/").get_data(as_text=True)
    # the guard helper still compares the snapshot against the live session (the load-bearing check)...
    assert "function sessionChanged(u, where)" in html
    assert "if (u === currentUser) return false" in html
    # ...and every renderer routes its bail through it (loadProfile/Dashboard/History/Forum/openPost/
    # loadConversations/renderThread/dmReply/syncEmailConsent).
    assert html.count('sessionChanged(u, "') >= 8
    # renderThread additionally guards a mid-flight thread switch
    assert "peer !== dmPeer" in html


def test_debug_tracing_is_gated_off_by_default(client):
    # a gated debug tracer (Week-9 "logging has a cost"): OFF for normal users, ON via ?debug=1 or
    # localStorage "ws-debug" — so the bug-prone async/session/SSE paths are traceable without spamming
    # a normal user's console. The #109 stale-paint site is instrumented.
    html = client.get("/").get_data(as_text=True)
    assert "function dbg(" in html and "if (DEBUG)" in html      # dbg no-ops unless the flag is set
    assert 'localStorage.getItem("ws-debug")' in html and 'has("debug")' in html
    assert 'dbg("stale paint bailed:' in html


def test_daily_checkin_section_present_and_wired(client):
    # the check-in form posts today's readiness metrics to /checkin.
    html = client.get("/").get_data(as_text=True)
    assert 'id="checkin-form"' in html
    assert "/checkin" in html
    for field in ["sleep_hours", "resting_hr", "fatigue", "soreness", "training_load"]:
        assert f'name="{field}"' in html


def test_register_hints_are_fetched_from_the_config_endpoint(client):
    # the credential hints are JS-driven from /auth/config (single source of truth), not hardcoded.
    html = client.get("/").get_data(as_text=True)
    assert 'class="info"' in html
    assert "/auth/config" in html
    assert 'id="reg-username-tip"' in html and 'id="reg-password-tip"' in html


def test_dark_mode_and_a11y_present(client):
    # dark mode done right (declared scheme + light-mode adaptation) + keyboard/label a11y.
    html = client.get("/").get_data(as_text=True)
    assert "color-scheme" in html                       # native controls/scrollbars match the theme
    assert "prefers-color-scheme: light" in html        # respects an OS light preference
    assert ":focus-visible" in html                     # visible focus ring for keyboard users
    assert 'for="age"' in html and 'id="age"' in html   # labels associated with their inputs


def test_theme_toggle_present_and_wired(client):
    # accessibility: a VISIBLE System/Light/Dark control (the OS-only theme had no in-app switch), applied
    # before first paint (no flash) and persisted across visits.
    html = client.get("/").get_data(as_text=True)
    assert 'id="theme-group"' in html                          # the settings control exists in the Profile screen
    for v in ('value="system"', 'value="light"', 'value="dark"'):
        assert v in html
    assert 'data-theme="light"' in html                        # the CSS overrides the OS via the forced-theme attr
    assert 'localStorage.getItem("ws-theme")' in html          # persisted + applied pre-paint in the <head> script
    assert "theme-switching" in html                           # transitions suppressed during the swap -> no flicker


def test_touch_targets_meet_44px_minimum(client):
    # a11y: the compact secondary controls (Refresh / comment votes / detail close ✕ / theme segments)
    # are enlarged to the 44px WCAG 2.5.5 tap-target minimum. Guards against a future edit silently
    # shrinking them back below the recommended target on a touch device.
    css = client.get("/").get_data(as_text=True)
    assert css.count("min-height:44px") >= 3       # button.mini, .detail .close, .settings-group .seg
    assert css.count("min-width:44px") >= 2        # button.mini (icon buttons), .detail .close
    assert "padding-right:44px" in css             # a long post title stays clear of the absolute close ✕


def test_account_editing_ui_present_and_wired(client):
    # the Account card exposes display-name + change-password editors, wired to the /account endpoints
    # (autocomplete tokens let a password manager fill current / suggest a new password).
    html = client.get("/").get_data(as_text=True)
    assert 'id="displayname-form"' in html and 'id="password-form"' in html
    assert "/account/display-name" in html and "/account/password" in html
    assert 'id="current-password"' in html and 'id="new-password"' in html
    assert 'autocomplete="current-password"' in html and 'autocomplete="new-password"' in html


def test_delete_account_ui_present_and_wired(client):
    # GDPR erasure: a two-step delete gated by BOTH the password AND a typed "DELETE" confirmation
    # (the "Delete forever" button stays disabled until the word matches), then DELETEs /account.
    html = client.get("/").get_data(as_text=True)
    assert 'id="delete-reveal"' in html and 'id="delete-form"' in html
    assert 'method: "DELETE"' in html and '"/account"' in html
    assert 'id="delete-password"' in html and 'id="delete-confirm"' in html
    assert "syncDeleteBtn" in html                      # button-gating logic is wired
    assert '!== "DELETE"' in html                       # stays disabled until the exact word is typed


def test_privacy_and_export_ui_present_and_wired(client):
    # GDPR: an email-consent opt-in toggle + a "download my data" export button, wired to the endpoints.
    html = client.get("/").get_data(as_text=True)
    assert 'id="email-consent"' in html and 'id="export-btn"' in html
    assert "/account/email-consent" in html and "/account/export" in html
    assert "worksmarter-export.json" in html            # the export triggers a JSON file download


def test_manifest_is_served_for_pwa(client):
    # the web manifest makes the app installable (name + icons + start_url), at the right mimetype.
    resp = client.get("/manifest.webmanifest")
    assert resp.status_code == 200
    assert "manifest" in resp.content_type              # application/manifest+json
    data = resp.get_json(force=True)
    assert data["name"] and data["icons"] and data["start_url"] == "/"


def test_service_worker_served_at_root_scope(client):
    # the SW is served from root with Service-Worker-Allowed:/ so it controls the whole app scope.
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    assert "javascript" in resp.content_type
    assert resp.headers.get("Service-Worker-Allowed") == "/"


def test_index_wires_the_pwa(client):
    # the shell links the manifest + theme-color + apple icon and registers the service worker.
    html = client.get("/").get_data(as_text=True)
    assert 'rel="manifest"' in html and 'name="theme-color"' in html
    assert 'rel="apple-touch-icon"' in html
    assert "serviceWorker" in html and "/sw.js" in html
