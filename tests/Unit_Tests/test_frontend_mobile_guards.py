"""Frontend guard tests — pin the mobile UX fixes so a future edit can't silently regress them.

These assert on the *served* template + static assets (structural markers, not pixels). They can't
prove the iOS-only behaviors render correctly on a real iPhone (overscroll colour, the home-screen
name), but they DO fail CI the moment the code that produces those behaviors is removed — which is
how the six issues from 2026-07-10 got reintroduced-proof. Cheap, deterministic, no browser needed.

The truly device-specific checks still need a human on an iPhone before a release — see
docs/MOBILE_SMOKE_TEST.md; these guards cover the "did someone delete the fix" failure mode.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "web" / "templates" / "index.html").read_text(encoding="utf-8")
MANIFEST = (ROOT / "web" / "static" / "manifest.webmanifest").read_text(encoding="utf-8")
SW = (ROOT / "web" / "static" / "sw.js").read_text(encoding="utf-8")


# ---- 1. PWA home-screen name stays short (iOS reads the manifest name, not apple-mobile-web-app-title) ----
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


# ---- 2. Every password field has a show/hide toggle ----
def test_password_fields_get_a_show_hide_toggle():
    assert "addPasswordToggles" in INDEX, "the password show/hide toggle injector was removed"
    assert ".pw-eye" in INDEX, "the eye-button CSS was removed"
    # every password input is a candidate the injector wraps
    assert INDEX.count('type="password"') >= 5, "expected the auth/settings password inputs to still exist"


# ---- 3. Forum posts expand inline (not a bottom panel) with a collapse chevron ----
def test_forum_posts_expand_inline_with_a_chevron():
    assert "function togglePost" in INDEX, "the forum expand/collapse toggle was removed"
    assert "function placeDetail" in INDEX, "the inline-detail placement (open-in-place) was removed"
    assert "post-chev" in INDEX, "the collapse chevron was removed"


# ---- 4. Theme segments can't overlap on mobile ----
def test_theme_segments_use_the_non_overlapping_row():
    assert 'class="seg-row"' in INDEX, "the theme segments lost their flex-row wrapper"
    assert ".settings-group .seg-row" in INDEX, "the .seg-row layout CSS was removed"


# ---- 5 + 6. Nav fills the viewport + overscroll shows the app colour, not white ----
def test_viewport_fill_and_overscroll_background():
    assert "min-height:100dvh" in INDEX, "body no longer fills the dynamic viewport (nav wobble returns)"
    assert re.search(r"html\s*\{[^}]*background-color:\s*var\(--bg\)", INDEX), \
        "html lost its theme background (iOS overscroll flashes white again)"


# ---- 7. The debug panel's viewport preview is desktop-only (pointless/redundant on a phone) ----
def test_viewport_preview_is_hidden_on_mobile():
    # The section keeps its id so the media query can target it...
    assert 'id="debug-vp-sect"' in INDEX, "the viewport-preview section lost its targetable id"
    # ...and a narrow-viewport media query hides exactly that section (the rest of the panel stays).
    assert re.search(r"@media\s*\(max-width:\s*859px\)\s*\{\s*#debug-vp-sect\s*\{\s*display:\s*none", INDEX), \
        "viewport preview must be hidden under the mobile breakpoint (redundant on a real phone)"


# ---- 8. Frosted-glass panels carry the -webkit- prefix (iOS Safari ignores the unprefixed one) ----
def test_glass_panels_have_the_webkit_backdrop_prefix_for_ios():
    # iOS Safari honors ONLY -webkit-backdrop-filter. The profile dropdown lost its blur on the phone
    # (page bled through) because it had backdrop-filter without the prefix — pin both panels.
    panel = re.search(r"\.usermenu-panel\s*\{[^}]*\}", INDEX, re.S).group(0)
    assert "-webkit-backdrop-filter" in panel, "usermenu dropdown needs -webkit-backdrop-filter or iOS drops the glass"
    tabbar = re.search(r"\.tabbar-inner\s*\{[^}]*\}", INDEX, re.S).group(0)
    assert "-webkit-backdrop-filter" in tabbar, "nav bar needs -webkit-backdrop-filter for its iOS glass"
