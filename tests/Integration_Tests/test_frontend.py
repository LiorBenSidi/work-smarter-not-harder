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
    for hook in ["login", "register", "profile", "dashboard", "history", "logout"]:
        assert hook in html


def test_index_references_every_api_endpoint(client):
    html = client.get("/").get_data(as_text=True)
    for endpoint in ["/register", "/login", "/logout", "/me", "/profile", "/dashboard", "/history"]:
        assert endpoint in html
