"""Static security & contract guards on the served frontend. OWNER: Lior.

These read the served template + static assets and assert real INVARIANTS — security properties
(no native-GET credential leak, XSS-escaping, reset-token scrubbing), config/model contracts (manifest
name length + cache-busting, the sleep_hours min matching the AI model, a fetch abort timeout), and a few
regression guards (readiness shows without a profile #266; a check-in prompt instead of a fake AI outage
#263).

They are static (no browser) but validate a genuine property — NOT "does this code string exist". The
cosmetic/duplicate UX greps that used to live here were removed on the rule that a test
must assert behaviour or an invariant, not mirror the implementation, and a test that isn't real shouldn't
stay. The UX behaviour they nominally covered is exercised for real by the browser E2E
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
    """A phone truncates the home-screen label at around a dozen characters, so all three name fields stay short enough to render intact instead of mangled."""
    name = re.search(r'"name"\s*:\s*"([^"]*)"', MANIFEST).group(1)
    short = re.search(r'"short_name"\s*:\s*"([^"]*)"', MANIFEST).group(1)
    # iOS truncates ~12 chars on the home screen; both must be short so the label never mangles.
    assert len(name) <= 14, f'manifest name too long for the home screen: {name!r}'
    assert len(short) <= 14, f'manifest short_name too long: {short!r}'
    apple = re.search(r'apple-mobile-web-app-title"\s+content="([^"]*)"', INDEX).group(1)
    assert len(apple) <= 14, f'apple-mobile-web-app-title too long: {apple!r}'


def test_manifest_url_is_versioned_so_a_new_name_actually_reaches_the_phone():
    """The manifest is cached aggressively, so a version marker on its URL is what forces an already-installed phone to pick up a renamed app instead of serving the stale copy.

    The service worker must cache that exact versioned URL, or the two disagree about which manifest is current.
    """
    link = re.search(r'rel="manifest"\s+href="([^"]*)"', INDEX).group(1)
    assert "?v=" in link, "manifest link must be versioned (?v=N) so a rename busts the cache"
    assert link in SW, f"SW SHELL must cache the exact versioned manifest URL {link!r} the page links"


# ---- EVERY frosted-glass panel carries the -webkit- prefix (iOS Safari ignores the unprefixed one) ----
def test_all_glass_panels_have_the_webkit_prefix_for_ios():
    """iOS Safari honours only the prefixed blur property, so a panel declaring the bare one loses its frosting on iPhone and the page bleeds through behind it.

    Checked across the whole file, so a newly-added panel cannot quietly reintroduce the bug.
    """
    css = re.sub(r"/\*.*?\*/", "", INDEX, flags=re.S)          # strip comments (prose mentions the property)
    plain = len(re.findall(r"(?<!-)\bbackdrop-filter:\s*blur", css))   # standalone (non -webkit-) decls
    webkit = len(re.findall(r"-webkit-backdrop-filter:\s*blur", css))
    assert plain and plain == webkit, (
        f"{plain} backdrop-filter blur decls but {webkit} -webkit- siblings — a glass panel loses iOS blur")


# ---- Media render is XSS-safe: attachment ids are encodeURIComponent'd into the /media/ url ----
def test_media_render_is_injection_safe():
    """An attachment id is percent-encoded into the media URL, so a crafted id cannot break out of the path and become markup."""
    assert 'mediaEmbedHtml' in INDEX
    assert re.search(r'"/media/"\s*\+\s*encodeURIComponent\(att\.id\)', INDEX), \
        "media urls must encodeURIComponent the id"


# ---- Auth forms can never native-GET-submit credentials into the URL ----
def test_auth_forms_cannot_native_get_submit_credentials():
    """If a submit fires BEFORE the JavaScript handler attaches — a slow load, or no JavaScript at all — a form with no method defaults to a native GET and puts the username and password in the URL.

    From there they reach the address bar, the history, the server logs and the Referer header. The inline guard closes that window at parse time, before any script runs.
    """
    for form_id in ("login-form", "register-form", "forgot-form", "reset-form", "otp-form"):
        m = re.search(r'<form id="' + form_id + r'"[^>]*>', INDEX)
        assert m, f"the {form_id} auth form is missing"
        assert 'onsubmit="return false"' in m.group(0), \
            f"{form_id} must have onsubmit=\"return false\" so it can never native-GET-submit credentials"
        assert "method=" not in m.group(0).lower(), \
            f"{form_id} must not declare a method (an explicit method=get would leak credentials)"


def test_in_app_password_form_also_blocks_native_get():
    """The settings password-change form carries a credential too, so it needs the same parse-time guard as the sign-in forms."""
    m = re.search(r'<form id="password-form"[^>]*>', INDEX)
    assert m and 'onsubmit="return false"' in m.group(0), \
        'the password-change form must have onsubmit="return false"'


def test_reset_token_is_scrubbed_from_the_url_immediately():
    """The reset token leaves the address bar and the history as soon as it is captured at boot — not only after a successful reset, which may never happen.

    It is stashed first so a service-worker reload cannot drop the user back to login, then the URL is scrubbed; both happen before any session call.
    """
    assert re.search(r'get\("reset_token"\)[\s\S]{0,700}history\.replaceState\(\{\},\s*"",\s*"/"\)', INDEX), \
        "init() must replaceState to strip reset_token from the URL right after capturing it"


def test_statcard_escapes_its_value():
    """This helper writes into innerHTML, so it escapes its value itself rather than trusting every future caller to remember to."""
    assert re.search(r"function statCard\([\s\S]{0,320}?escapeHtml\(val\)", INDEX), \
        "statCard must escape val before inserting it into innerHTML"


# ---- The check-in sleep input matches the AI model's contract (min sleep_hours) ----
def test_sleep_input_min_matches_the_model_contract():
    """The client's accepted floor must match what the model accepts, or a user can submit a value the app stores happily and the model then refuses to score.

    The fields are typed rather than native number inputs — so the caret can sit mid-value and the numeric keypad still shows — which puts the floor in the JavaScript range, not an attribute.
    """
    m = re.search(r'<input id="sleep_hours"[^>]*>', INDEX)
    assert m, "the sleep_hours input is missing"
    assert 'inputmode="decimal"' in m.group(0), "the sleep input keeps the numeric keypad via inputmode"
    assert "CI_RANGE = { sleep_hours: [1, 24]" in INDEX, "the JS validation floor for sleep must be 1 (the model rejects < 1), not 0"


def test_api_fetch_has_an_abort_timeout():
    """A HUNG request — not a clean failure — would spin the loading skeleton forever, so every call arms an abort timer and falls into the ordinary error path instead."""
    assert "AbortController" in INDEX, "api() must arm an AbortController timeout so a hung request can't spin forever"
    assert re.search(r"setTimeout\(\(\)\s*=>\s*ctrl\.abort\(\),\s*\d{4,}\)", INDEX), \
        "the abort timer must fire after a bounded delay"
    assert "opts.signal" in INDEX, "the fetch must actually receive the abort signal"


def test_auth_view_is_hidden_by_default_to_avoid_a_landing_flash():
    """The landing view starts hidden, so reloading while signed in does not flash the logged-out page before the session check resolves."""
    m = re.search(r'<section id="auth-view"([^>]*)>', INDEX)
    assert m and "hidden" in m.group(1), "#auth-view must be hidden by default (revealed after GET /me)"


def test_loaddashboard_guards_a_null_body():
    """A 200 carrying an empty or unparseable body must not throw mid-render, so a momentary backend hiccup does not blank the dashboard."""
    assert "const d = r.data || {};" in INDEX, "loadDashboard must default r.data to {} so a null body can't throw"


# ---- Dashboard readiness regressions (#266 / #263) ----
def test_dashboard_readiness_does_not_hard_require_a_profile():
    """A missing profile must not suppress the readiness score — it gates only the calorie target — so someone who has checked in still sees the number they came for, with a soft prompt for the rest."""
    assert not re.search(r"if\s*\(\s*d\.needs_profile\s*\)\s*\{", INDEX), \
        "needs_profile must not early-return/suppress the dashboard (readiness shows without a profile)"
    # instead it's a soft nudge for the calorie target when the orb is shown
    assert "Set up your profile to get a daily calorie target." in INDEX, \
        "when readiness shows without a profile, the UI must softly prompt a profile for the calorie target"


def test_dashboard_prompts_a_checkin_instead_of_faking_an_ai_outage():
    """With a profile but no check-in there is nothing to score, so the dashboard asks for a check-in rather than reporting the AI as down.

    Without this, every brand-new user's first impression is a false outage.
    """
    assert "d.needs_checkin" in INDEX, "the dashboard must handle the needs_checkin state"
    assert "Log today's check-in to see your readiness." in INDEX, \
        "the needs_checkin branch must prompt the check-in"


# ---- Identifier inputs must not be auto-capitalised by the phone keyboard ----
# id -> what the typed value is matched against, and what an inserted capital costs.
IDENTIFIER_INPUTS = {
    "login-username": "the login identifier — auth.py resolves a handle with an exact _users().get(), "
                      "so a capital becomes 'invalid username or password'",
    "dm-to": "the DM recipient — messages.py rejects an unresolved handle with 404 'no such user', "
             "so a capital fails to start a conversation with a real person",
}


def test_identifier_inputs_suppress_phone_autocapitalisation():
    """A phone keyboard capitalises the first letter of a plain text input, and these two fields hold values the server matches EXACTLY, so an inserted capital turns a correct identifier into a failed login or a 404.

    The attribute IS the whole mechanism here: the browser reads it, and there is no code path
    underneath that could make the behaviour true or false independently. That is why this is a
    contract check rather than one of the "does this string exist" greps this file bans — there is
    nothing deeper to assert, and no browser in CI capitalises anything to assert it against.

    The server half is proven behaviourally elsewhere: Integration_Tests/test_auth_flow.py
    test_usernames_are_case_sensitive shows that distinct capitalisation makes distinct accounts,
    which is precisely why the capital must never be inserted on the client.

    Deliberately NOT in this set: #reg-username. It is labelled "Display name", the form tells the
    user they will sign in with their email, and it is shown to other people — a name should keep
    its capital.
    """
    for input_id, why in IDENTIFIER_INPUTS.items():
        tag = re.search(r"<input\b[^>]*\bid=\"" + re.escape(input_id) + r"\"[^>]*>", INDEX)
        assert tag, f"#{input_id} is missing from the template"
        markup = tag.group(0)
        assert 'autocapitalize="none"' in markup, \
            f'#{input_id} must declare autocapitalize="none" — {why}'
        assert 'autocorrect="off"' in markup, \
            f'#{input_id} must declare autocorrect="off" — an identifier has to arrive exactly as typed'
