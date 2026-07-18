"""Static security & contract guards on the served frontend. OWNER: Lior.

These read the served template + static assets and assert real INVARIANTS — security properties
(no native-GET credential leak, XSS-escaping, reset-token scrubbing), config/model contracts (manifest
name length + cache-busting, the sleep_hours min matching the AI model, a fetch abort timeout), and a few
regression guards (readiness shows without a profile #266; a check-in prompt instead of a fake AI outage
#263).

They are static (no browser) but validate a genuine property — NOT "does this code string exist". The
cosmetic/duplicate UX greps that used to live here were removed per the course's test-quality rule (a test
must assert behaviour or an invariant, not mirror the implementation, and a test that isn't real shouldn't
stay). The UX behaviour they nominally covered is exercised for real by the browser E2E
nav/responsive/forum scenarios (tests/E2E_Tests) and, for device-specific rendering, by the manual smoke
test (docs/MOBILE_SMOKE_TEST.md).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
MANIFEST = (ROOT / "web" / "static" / "manifest.webmanifest").read_text(encoding="utf-8")
SW = (ROOT / "web" / "static" / "sw.js").read_text(encoding="utf-8")


# ---- PWA home-screen name stays short (iOS reads the manifest name, not apple-mobile-web-app-title) ----
def test_pwa_names_are_short_enough_for_the_home_screen():
    name = re.search(r'"name"\s*:\s*"([^"]*)"', MANIFEST).group(1)
    short = re.search(r'"short_name"\s*:\s*"([^"]*)"', MANIFEST).group(1)
    # iOS truncates ~12 chars on the home screen; both must be short so the label never mangles.
    assert len(name) <= 14, f'manifest name too long for the home screen: {name!r}'
    assert len(short) <= 14, f'manifest short_name too long: {short!r}'
    apple = re.search(r'apple-mobile-web-app-title"\s+content="([^"]*)"', INDEX).group(1)
    assert len(apple) <= 14, f'apple-mobile-web-app-title too long: {apple!r}'


def test_manifest_url_is_versioned_so_a_new_name_actually_reaches_the_phone():
    # The manifest is cached (SW cache-first + a 24h HTTP max-age). A ?v= bump is what forces the
    # phone to fetch a renamed manifest instead of serving the stale one.
    link = re.search(r'rel="manifest"\s+href="([^"]*)"', INDEX).group(1)
    assert "?v=" in link, "manifest link must be versioned (?v=N) so a rename busts the cache"
    assert link in SW, f"SW SHELL must cache the exact versioned manifest URL {link!r} the page links"


# ---- EVERY frosted-glass panel carries the -webkit- prefix (iOS Safari ignores the unprefixed one) ----
def test_all_glass_panels_have_the_webkit_prefix_for_ios():
    # iOS Safari honors ONLY -webkit-backdrop-filter. Any panel with a bare backdrop-filter loses its blur
    # on iPhone (the page bleeds through — how the profile dropdown regressed). Pin the WHOLE file: every
    # backdrop-filter: blur declaration must have a -webkit- sibling, so a new panel can't reintroduce it.
    css = re.sub(r"/\*.*?\*/", "", INDEX, flags=re.S)          # strip comments (prose mentions the property)
    plain = len(re.findall(r"(?<!-)\bbackdrop-filter:\s*blur", css))   # standalone (non -webkit-) decls
    webkit = len(re.findall(r"-webkit-backdrop-filter:\s*blur", css))
    assert plain and plain == webkit, (
        f"{plain} backdrop-filter blur decls but {webkit} -webkit- siblings — a glass panel loses iOS blur")


# ---- Media render is XSS-safe: attachment ids are encodeURIComponent'd into the /media/ url ----
def test_media_render_is_injection_safe():
    # attachment ids come from the server as opaque hex; the embed builds /media/<id> with encodeURIComponent
    # and images/video load via src (no innerHTML of user text). Pin the encode so an id can't break out.
    assert 'mediaEmbedHtml' in INDEX
    assert re.search(r'"/media/"\s*\+\s*encodeURIComponent\(att\.id\)', INDEX), \
        "media urls must encodeURIComponent the id"


# ---- Auth forms can never native-GET-submit credentials into the URL ----
def test_auth_forms_cannot_native_get_submit_credentials():
    # Security (defense-in-depth): every auth form's JS submit handler POSTs via fetch, but if a submit
    # fires BEFORE that script attaches (slow load / no-JS), a form with no method defaults to a native
    # GET -> username & password land in the URL (?username=...&password=...) and leak into the address
    # bar, history, server logs, and Referer. `onsubmit="return false"` closes that window at parse time.
    for form_id in ("login-form", "register-form", "forgot-form", "reset-form", "otp-form"):
        m = re.search(r'<form id="' + form_id + r'"[^>]*>', INDEX)
        assert m, f"the {form_id} auth form is missing"
        assert 'onsubmit="return false"' in m.group(0), \
            f"{form_id} must have onsubmit=\"return false\" so it can never native-GET-submit credentials"
        assert "method=" not in m.group(0).lower(), \
            f"{form_id} must not declare a method (an explicit method=get would leak credentials)"


def test_in_app_password_form_also_blocks_native_get():
    # L2: the settings password-change form carries password fields; give it the same onsubmit guard as
    # the auth forms so it can never native-GET-submit a credential.
    m = re.search(r'<form id="password-form"[^>]*>', INDEX)
    assert m and 'onsubmit="return false"' in m.group(0), \
        'the password-change form must have onsubmit="return false"'


def test_reset_token_is_scrubbed_from_the_url_immediately():
    # L3: the reset token must leave the address bar/history as soon as it's captured at boot, not only
    # after a successful reset (the form reads the JS var, not the URL).
    # (window widened for the SW-reload hardening: the token is stashed in sessionStorage first — so it
    # survives a service-worker auto-reload that would otherwise drop the reset to login — then the URL is
    # scrubbed. Both still happen at capture, before any /me call.)
    assert re.search(r'get\("reset_token"\)[\s\S]{0,700}history\.replaceState\(\{\},\s*"",\s*"/"\)', INDEX), \
        "init() must replaceState to strip reset_token from the URL right after capturing it"


def test_statcard_escapes_its_value():
    # L5: statCard is an innerHTML sink; it must escape val internally so a future string caller can't XSS.
    assert re.search(r"function statCard\([\s\S]{0,320}?escapeHtml\(val\)", INDEX), \
        "statCard must escape val before inserting it into innerHTML"


# ---- The check-in sleep input matches the AI model's contract (min sleep_hours) ----
def test_sleep_input_min_matches_the_model_contract():
    # F1: the ai model rejects sleep_hours < 1. The typed check-in fields are text+inputmode (so the caret can
    # sit at the end of a partly-typed value and iOS still shows the numeric keypad), so the >= 1 floor lives in
    # the JS validation range (CI_RANGE) + the server, not a native min= attribute. Guard the JS floor here.
    m = re.search(r'<input id="sleep_hours"[^>]*>', INDEX)
    assert m, "the sleep_hours input is missing"
    assert 'inputmode="decimal"' in m.group(0), "the sleep input keeps the numeric keypad via inputmode"
    assert "CI_RANGE = { sleep_hours: [1, 24]" in INDEX, "the JS validation floor for sleep must be 1 (the model rejects < 1), not 0"


def test_api_fetch_has_an_abort_timeout():
    # P1: a HUNG request (not a clean drop) would spin the skeleton forever. api() arms an AbortController
    # so a wedged request rejects and falls back to the {ok:false} error path.
    assert "AbortController" in INDEX, "api() must arm an AbortController timeout so a hung request can't spin forever"
    assert re.search(r"setTimeout\(\(\)\s*=>\s*ctrl\.abort\(\),\s*\d{4,}\)", INDEX), \
        "the abort timer must fire after a bounded delay"
    assert "opts.signal" in INDEX, "the fetch must actually receive the abort signal"


def test_auth_view_is_hidden_by_default_to_avoid_a_landing_flash():
    # P2: #auth-view must start hidden so a reload-while-logged-in doesn't flash the marketing/login
    # landing before GET /me resolves and reveals the app.
    m = re.search(r'<section id="auth-view"([^>]*)>', INDEX)
    assert m and "hidden" in m.group(1), "#auth-view must be hidden by default (revealed after GET /me)"


def test_loaddashboard_guards_a_null_body():
    # P3: a 200 with a null/unparseable body must not throw on d.readiness (mirrors the other loaders).
    assert "const d = r.data || {};" in INDEX, "loadDashboard must default r.data to {} so a null body can't throw"


# ---- Dashboard readiness regressions (#266 / #263) ----
def test_dashboard_readiness_does_not_hard_require_a_profile():
    # Issue #266: a missing profile must NOT suppress the readiness orb (it only gates the calorie target).
    # There must be no `if (d.needs_profile) { ... return; }` early-return that shows the Example card.
    assert not re.search(r"if\s*\(\s*d\.needs_profile\s*\)\s*\{", INDEX), \
        "needs_profile must not early-return/suppress the dashboard (readiness shows without a profile)"
    # instead it's a soft nudge for the calorie target when the orb is shown
    assert "Set up your profile to get a daily calorie target." in INDEX, \
        "when readiness shows without a profile, the UI must softly prompt a profile for the calorie target"


def test_dashboard_prompts_a_checkin_instead_of_faking_an_ai_outage():
    # With a profile but no check-in there are no metrics to score, so the dashboard returns
    # needs_checkin (not ai_status 'unavailable'). The UI must render the check-in prompt for that
    # state, NOT the "AI service down" warning — otherwise a brand-new user sees a false outage.
    assert "d.needs_checkin" in INDEX, "the dashboard must handle the needs_checkin state"
    assert "Log today's check-in to see your readiness." in INDEX, \
        "the needs_checkin branch must prompt the check-in"
