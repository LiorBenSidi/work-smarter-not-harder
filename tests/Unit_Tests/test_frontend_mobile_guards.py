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


# ---- 2b. The logged-out landing is an editorial split with a LIVE readiness demo (not a centred column) ----
def test_landing_is_editorial_split_with_live_demo():
    # The generic-landing look (centred single column + boxed 01/02/03 steps) was replaced by a two-column
    # thesis/auth split whose signature is a live sample of the product's one output.
    assert ".auth-split" in INDEX, "the editorial thesis/auth split was removed"
    assert 'class="readiness-demo"' in INDEX, "the live readiness demo (orb + readout) was removed"
    assert 'id="demo-state"' in INDEX and 'id="demo-verb"' in INDEX, "the demo state/verb readout was removed"
    assert 'class="auth-steps"' in INDEX and INDEX.count('<li>') >= 3, "the 3 how-it-works steps were removed"
    # the old boxed/numbered treatment must NOT come back (an AI-landing tell)
    assert 'class="how"' not in INDEX and "how-n" not in INDEX, "the boxed 01/02/03 steps must stay gone"
    # the value paragraph was removed (it duplicated the 3 steps) — the steps are the single "how it works"
    assert "hero-sub" not in INDEX, "the redundant landing value paragraph (hero-sub) must stay removed"


# ---- 2b2. On mobile the orb is at the top and the login card is reachable without scrolling ----
def test_mobile_landing_orb_top_and_login_reachable():
    # Mobile flattens the split (display:contents) and orders the column so the orb is first (top) and the
    # auth card comes right after the headline -> login/register reachable without scrolling. On mobile the
    # value paragraph is dropped and the 3 steps carry the "how". Desktop's editorial split is untouched.
    assert re.search(r"\.auth-thesis\s*\{\s*display:\s*contents", INDEX), \
        "mobile must flatten the split (display:contents) so the pieces can be reordered"
    assert re.search(r"\.readiness-demo\s*\{\s*order:\s*1", INDEX), "the orb demo must be first (top) on mobile"
    assert re.search(r"\.auth-panel\s*\{\s*order:\s*4", INDEX), \
        "the auth card must sit right under the headline (order:4) so login is reachable without scrolling"
    assert re.search(r"\.auth-steps\s*\{\s*order:\s*5", INDEX), "the 3 steps must be shown (ordered) on mobile"


# ---- 2c. The landing orb cycles the 3 states with a SMOOTH crossfade + is reduced-motion safe ----
def test_landing_orb_cycles_states_and_crossfades():
    # A live sample: the aurora colour + readout cycle Ready -> Moderate -> Rest, easing between colours
    # (a per-frame lerp) rather than snapping, and staying static under reduced motion.
    for state in ("Ready", "Moderate", "Rest"):
        assert state in INDEX, f"the landing demo lost the {state!r} state"
    # per-frame colour easing toward the target (the natural crossfade) — the interpolation term must exist
    assert re.search(r"target\[i\]\[k\]\s*-\s*v\)\s*\*\s*0?\.\d+", INDEX), \
        "the orb colour must ease toward the target per frame (crossfade), not snap"
    # reduced-motion: paint one static state and return (no cycling loop) — JS RAF isn't covered by CSS
    assert re.search(r"if\s*\(reduce\)\s*\{\s*setState\(0\);\s*paint\([^)]*\);\s*return;", INDEX), \
        "under reduced motion the orb must paint one static state and not cycle"


# ---- 2d. Motion + material polish (design pass): solid-mint primary, calm motion (no ambient loops) ----
def test_primary_controls_are_solid_mint_not_gradient():
    # One tinted colour per view (iOS 26); a gradient-to-lilac primary button is an AI-output tell. The
    # primary button, active auth tab, and active menu segment fill with a solid --accent.
    assert re.search(r"\bbutton\s*\{\s*background:\s*var\(--accent\);", INDEX), \
        "the primary button must be solid mint (var(--accent)), not a gradient toward lilac"
    assert re.search(r"\.tabs button\.active\s*\{\s*background:\s*var\(--accent\);", INDEX), \
        "the active auth tab must be solid mint"


def test_forum_controls_use_svg_icons_not_unicode_glyphs():
    # The ▲▾✕▼ template glyphs (inconsistent weight/baseline across platforms) are replaced by the app's SVG
    # icon set — score/vote/close/chevron all render from ICON.up/down/close/chev.
    assert "close:" in INDEX and "chev:" in INDEX, "the close/chev SVG icons were removed from the ICON set"
    assert "ICON.close" in INDEX, "the detail close button must use the SVG close icon"
    assert "ICON.chev" in INDEX, "the post chevron must be the SVG chev icon"
    assert "ICON.up + ' up" in INDEX and "ICON.down + ' down" in INDEX, "vote buttons must use SVG up/down icons"
    for g in (">▲<", ">▼<", ">✕<", ">▾<"):   # ▲ ▼ ✕ ▾ inside a rendered element
        assert g not in INDEX, "no unicode vote/close glyph may remain in the rendered markup (SVG icons only)"


def test_content_cards_are_de_glassed():
    # iOS 26: glass is a NAV-layer material only; content cards are solid (no backdrop-filter). The nav
    # layer (header, tab pill, menus, tooltips) keeps its glass — this only de-glasses .card / .stat.
    assert "--card-solid" in INDEX and "--stat-solid" in INDEX, "the solid content-surface tokens were removed"
    card_rule = re.search(r"\.card\s*\{([^}]*)\}", INDEX).group(1)
    assert "var(--card-solid)" in card_rule, ".card must use the solid content surface (--card-solid)"
    assert "backdrop-filter" not in card_rule, ".card must NOT have a backdrop-filter (content is solid, glass is nav-only)"
    stat_rule = re.search(r"\.stat\s*\{([^}]*)\}", INDEX).group(1)
    assert "var(--stat-solid)" in stat_rule and "backdrop-filter" not in stat_rule, ".stat must be solid too"


def test_today_leads_with_a_real_0_100_score():
    # The Today orb leads with a 0-100 readiness SCORE (mono) as the one loud number, verdict word beneath
    # (Whoop/Oura single-metric hero). The score is derived from the model's real class distribution (proba),
    # not invented — the helper weights the classes and normalises by the total probability.
    assert "function readinessScore" in INDEX, "the readinessScore helper (real 0-100 from proba) was removed"
    assert re.search(r"readinessScore\(readiness\)\s*\{[^}]*?readiness\.proba", INDEX, re.S), \
        "readinessScore must derive the number from the model's proba distribution (not a fixed/invented value)"
    assert re.search(r'class="score"[^>]*>\'\s*\+\s*score', INDEX), "the orb must render the numeric score as its hero"
    assert '"verdict-sub"' in INDEX and re.search(r"\.score\s*\{[^}]*font-family:var\(--font-mono\)", INDEX), \
        "the score must use the mono instrument face with the verdict word as a sub-label"


def test_ambient_animation_loops_are_calmed():
    # Only the hero orb(s) breathe; the brand-dot breathe, the readiness-orb halo pulse, and the signal
    # 'beat' were removed (5 simultaneous ambient loops read busy/AI-generated). Their keyframes are gone too.
    assert "@keyframes halo" not in INDEX, "the halo pulse keyframe must stay removed (calm motion)"
    assert "@keyframes beat" not in INDEX, "the signal 'beat' keyframe must stay removed (calm motion)"
    assert "animation: halo" not in INDEX and "animation: beat" not in INDEX, \
        "no element may use the removed halo/beat ambient loops"
    # the press-state physics that make taps feel native stay
    assert re.search(r"button:active\s*\{\s*transform:\s*scale\(\.97\)", INDEX), \
        "buttons must keep the scale-down press physics (native tactility)"


# ---- 3a. Voting must not destroy #forum-detail (the "can't open any post after voting" wedge, 2026-07-11) ----
def test_forum_detail_is_stashed_before_any_list_wipe():
    # When a post is open, #forum-detail is slotted INSIDE #forum-list. loadForum() (called by vote())
    # wipes the list's innerHTML; without moving the detail out first it is DESTROYED, and every later
    # openPost throws on a null box -> the forum wedges. Both list-wipers must stashDetail() first, and
    # openPost must guard a null box so a missing detail degrades to a retry rather than a throw.
    assert "function stashDetail" in INDEX, "the stashDetail rescue helper (un-wedge after voting) was removed"
    assert re.search(r"stashDetail\(\);[^\n]*\n\s*el\.innerHTML\s*=\s*'<p class=\"muted\">Loading", INDEX), \
        "loadForum must stashDetail() before wiping #forum-list (else voting destroys #forum-detail)"
    # renderForumList also stashes before it rebuilds the list
    assert re.search(r"function renderForumList\(\)\s*\{[^}]*?stashDetail\(\);", INDEX), \
        "renderForumList must stashDetail() before rebuilding the list"
    # openPost degrades gracefully if the detail box is somehow missing (no TypeError-wedge)
    assert re.search(r"if\s*\(!box\s*\|\|\s*!r\.ok", INDEX), \
        "openPost must guard a null #forum-detail box so a missing element can't throw-and-wedge"


# ---- 3. Forum posts expand inline (not a bottom panel) with a collapse chevron ----
def test_forum_posts_expand_inline_with_a_chevron():
    assert "function togglePost" in INDEX, "the forum expand/collapse toggle was removed"
    assert "function placeDetail" in INDEX, "the inline-detail placement (open-in-place) was removed"
    assert "post-chev" in INDEX, "the collapse chevron was removed"


# ---- 3b. A failed post-open must never WEDGE the forum (the iOS "can't open any post" bug, 2026-07-11) ----
def test_forum_open_failure_never_wedges():
    # currentPostId is set BEFORE the detail fetch, so ANY bail that leaves it set makes the post keep its
    # .open border on every re-render with no detail, unrecoverable by nav-away-and-back. Both failure modes
    # — a REJECTED fetch (flaky mobile network; api() re-throws) and a non-ok / malformed response — must
    # route through failOpen(), which clears currentPostId + the border and surfaces a retry hint.
    assert "function failOpen" in INDEX, "the failOpen reset helper (un-wedge on a failed open) was removed"
    # failOpen bails on a superseded open (seq guard), then clears the stuck state via closePost().
    assert re.search(r"function failOpen\(seq\)\s*\{[^}]*?if\s*\(seq\s*!==\s*openPostSeq\)\s*return;[^}]*?closePost\(\);", INDEX), \
        "failOpen must bail on a superseded seq, then closePost() to clear currentPostId + the .open border"
    # openPost wraps the detail fetch so a REJECTED fetch calls failOpen instead of an unhandled rejection.
    assert re.search(r"try\s*\{\s*r\s*=\s*await\s+api\([^)]*\);\s*\}\s*catch\s*\([^)]*\)\s*\{\s*failOpen\(seq\);\s*return;", INDEX), \
        "openPost must catch a rejected detail fetch and call failOpen (else a dropped request wedges the forum)"
    # A null box / non-ok / body-without-.post response also routes through failOpen (not a silent hide/throw).
    assert re.search(r"if\s*\(!box\s*\|\|\s*!r\.ok\s*\|\|\s*!r\.data\s*\|\|\s*!r\.data\.post\)\s*\{\s*failOpen\(seq\);\s*return;", INDEX), \
        "a null box / non-ok / malformed detail response must call failOpen, not silently hide the box and leave state stuck"


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


# ---- 8. EVERY frosted-glass panel carries the -webkit- prefix (iOS Safari ignores the unprefixed one) ----
def test_all_glass_panels_have_the_webkit_prefix_for_ios():
    # iOS Safari honors ONLY -webkit-backdrop-filter. Any panel with a bare backdrop-filter loses its blur
    # on iPhone (the page bleeds through — how the profile dropdown regressed). Pin the WHOLE file: every
    # backdrop-filter: blur declaration must have a -webkit- sibling, so a new panel can't reintroduce it.
    css = re.sub(r"/\*.*?\*/", "", INDEX, flags=re.S)          # strip comments (prose mentions the property)
    plain = len(re.findall(r"(?<!-)\bbackdrop-filter:\s*blur", css))   # standalone (non -webkit-) decls
    webkit = len(re.findall(r"-webkit-backdrop-filter:\s*blur", css))
    assert plain and plain == webkit, (
        f"{plain} backdrop-filter blur decls but {webkit} -webkit- siblings — a glass panel loses iOS blur")


# ---- 9. The hero display face is wired end-to-end (self-hosted, preloaded, offline-cached, applied) ----
def test_hero_display_face_is_wired():
    font = "/static/fonts/bricolage-800-latin-v1.woff2"
    # @font-face declares it + a --font-display token points at it + the hero H1 uses that token.
    assert "@font-face" in INDEX and font in INDEX, "the self-hosted display @font-face/src was removed"
    assert "--font-display" in INDEX, "the --font-display token was removed"
    assert re.search(r"\.hero-title\s*\{[^}]*font-family:\s*var\(--font-display\)", INDEX), \
        "the hero H1 no longer uses the display face"
    # Preloaded (small FOUT window) with crossorigin (fonts fetch anonymous even same-origin).
    assert re.search(r'rel="preload"[^>]*' + re.escape(font) + r'[^>]*crossorigin', INDEX) or \
           re.search(re.escape(font) + r'"[^>]*as="font"[^>]*crossorigin', INDEX), \
        "the display font is not preloaded with crossorigin"
    # Cached offline as a BEST-EFFORT extra (a 404 must not fail the SW install / stall auto-update).
    assert font in SW and "SHELL_OPTIONAL" in SW, "the font must be in the SW's non-fatal SHELL_OPTIONAL"
    assert ".catch(() => {})" in SW, "the optional-shell add must swallow errors so a 404 can't stall install"


# ---- 10. The check-in reveal is orchestrated + reduced-motion-safe + race-free ----
def test_checkin_reveal_is_orchestrated_and_guarded():
    # kcal counts up (once, after both loaders settle) and the recs cascade — only on a FRESH check-in.
    assert "function countUpKcal" in INDEX and "function reducedMotion" in INDEX, "the reveal helpers were removed"
    assert "@keyframes recIn" in INDEX, "the recommendations cascade keyframe was removed"
    # Race fix: the check-in path awaits BOTH loaders, then counts up once (not from inside renderStats).
    assert re.search(r"Promise\.all\(\[\s*loadDashboard\(\{\s*fresh:\s*true\s*\}\),\s*loadHistory\(\)\s*\]\)", INDEX), \
        "check-in must await both loaders before the count-up (else the double render clobbers the tween)"
    assert "countUpKcal();" in INDEX, "the count-up is no longer kicked after the reveal settles"
    # Reduced-motion snap (JS RAF isn't covered by the CSS kill-switch) + NaN bail for the '—' empty state.
    assert re.search(r"function countUpKcal\(\)\s*\{\s*if\s*\(reducedMotion\(\)\)\s*return", INDEX), \
        "countUpKcal must bail to a snap under reduced motion"
    assert "Number.isFinite(target)" in INDEX, "count-up must bail on a non-numeric ('—') kcal value"
    # The refresh button must NOT pass its MouseEvent as opts (would truthy-trigger the fresh reveal).
    assert re.search(r'dashboard-refresh"\)\.addEventListener\("click",\s*\(\)\s*=>\s*loadDashboard\(\)\)', INDEX), \
        "the refresh listener must be wrapped so the click event isn't passed as opts"


# ---- 11. The hero accent stays a solid colour (gradient-clipped heading text is an AI-output tell) ----
def test_hero_accent_is_not_gradient_text():
    m = re.search(r"\.hero-title \.accent\s*\{[^}]*\}", INDEX)
    assert m, "the hero accent rule is missing"
    rule = m.group(0)
    assert "background-clip" not in rule and "color: var(--accent)" in rule, \
        "hero accent must be a solid colour, not gradient-clipped text (Impeccable's gradient-text detector)"


# ---- 12. Every numeric readout uses the mono "instrument" face (type-system consistency) ----
def test_streak_number_uses_mono():
    m = re.search(r"\.streak-n\s*\{[^}]*\}", INDEX)
    assert m and "font-family:var(--font-mono)" in m.group(0), \
        "the streak count must use --font-mono like every other number (the one that used to break the system)"
