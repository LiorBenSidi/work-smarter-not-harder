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
