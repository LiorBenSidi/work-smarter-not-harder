"""The /presentation route — a standalone, isolated pitch deck. OWNER: Lior.

The deck is rendered by the app in its own visual tone, but it is DELIBERATELY ISOLATED from the SPA:
public (no auth), self-contained (no app JS, no API calls, no session), and it renders no user-supplied
data — the only input is ?slide=N, parsed + clamped client-side and never inserted as HTML. These tests
pin that isolation so a future edit can't turn the deck into an attack surface into the app.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PRES = (ROOT / "web" / "templates" / "presentation.html").read_text(encoding="utf-8")


def test_presentation_route_is_public_and_serves_the_deck(client):
    r = client.get("/presentation")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("Content-Type", "")
    body = r.get_data(as_text=True)
    assert "Work Smarter, Not Harder" in body
    assert body.count('class="wp-slide"') == 8          # the 8 approved slides (Elad's Canva structure)


def test_presentation_needs_no_login(client):
    # It's a public marketing surface — reachable without a session, unlike the app's gated routes.
    assert client.get("/presentation").status_code == 200


def test_presentation_is_isolated_from_the_app():
    # The deck must share NO code with the SPA: no API calls, no session/auth, no app storage. If any of
    # these appear, the "independent page, no attack surface" guarantee (the reason it's a separate route)
    # is broken.
    for banned in ["fetch(", "XMLHttpRequest", " api(", "/me", "/login", "X-CSRF", "csrf_token",
                   "localStorage", "sessionStorage", "credentials:", "document.cookie"]:
        assert banned not in PRES, f"the presentation must not use {banned!r} — it must stay isolated from the app"


def test_presentation_slide_param_is_not_an_html_sink():
    # ?slide=N is the only external input. It must be parsed to an int and clamped to a slide index, never
    # inserted into the DOM as HTML (no innerHTML anywhere in the deck — all slide content is static markup).
    assert "parseInt(new URLSearchParams(location.search).get(\"slide\")" in PRES
    assert "Math.max(0, Math.min(total - 1, n))" in PRES
    assert "innerHTML" not in PRES, "the deck must not use innerHTML (keeps ?slide and all content injection-free)"


def test_presentation_route_does_not_touch_the_index_shell(client):
    # The deck is a separate template — hitting it must not require or alter the SPA shell.
    assert "wp-slide" not in client.get("/").get_data(as_text=True)   # the app shell has no deck markup
