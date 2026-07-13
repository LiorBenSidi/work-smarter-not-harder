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


def test_chat_bubbles_group_by_sender():
    # Signal-style grouping: the tail (pointed corner) + the time/Seen meta ride ONLY the last bubble of a
    # same-sender run, and continuation bubbles tuck tighter (.cont) — a run reads as one unit, not N stamped
    # bubbles. The base bubble no longer carries a tail unconditionally.
    assert re.search(r"\.bubble\.tail\.me\s*\{[^}]*border-bottom-right-radius", INDEX), "the tail must be run-end-only now"
    assert re.search(r"\.bubble\.cont\s*\{[^}]*margin-top:-", INDEX), "consecutive same-sender bubbles must tuck tighter"
    assert "const runEnd" in INDEX and "const cont" in INDEX, "the run grouping logic was removed"
    assert 'runEnd ? " tail"' in INDEX, "the tail must ride only the run-end bubble"


def test_chat_thread_is_a_real_messenger():
    # Chat now carries the WhatsApp bubble contract: per-bubble times + day separators + a "Seen" read state,
    # and a growing multiline compose with Enter-to-send (not a single-line input).
    assert "function clockTime" in INDEX and "function dayLabel" in INDEX, "the chat time helpers were removed"
    assert "dm-daysep" in INDEX and "dm-meta" in INDEX, "the date separators / bubble time meta were removed"
    assert "· Seen" in INDEX, "the read-state 'Seen' indicator was removed"
    assert '<textarea id="dm-reply"' in INDEX and "function autoGrow" in INDEX, \
        "the reply compose must be a growing textarea (Enter-to-send), not a single-line input"


def test_history_rows_are_a_colour_coded_score_column():
    # History rows lead with the numeric readiness score + a state-colour dot + a RELATIVE time (Whoop trend
    # tier) — not a flat "<strong>word</strong> raw-ISO-timestamp" line.
    assert "function timeAgoStr" in INDEX, "the ISO relative-time helper for history rows was removed"
    assert "timeAgoStr(it.timestamp)" in INDEX, "history rows must show a relative time, not the raw ISO string"
    assert 'class="hrow' in INDEX and "hrow-score" in INDEX, "the colour-coded history row markup was removed"
    assert re.search(r"\.hrow-score\s*\{[^}]*color:var\(--st\)", INDEX), "the history score must be state-coloured (--st)"


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
    assert re.search(r"stashDetail\(\);[^\n]*\n\s*el\.innerHTML\s*=\s*sk\(", INDEX), \
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


def test_ios_scroll_behaviors():
    # iOS-26 / Instagram scroll feel: the header is clean at the top and frosts once content scrolls under it; the
    # MOBILE tab bar (+ Home FAB) SHRINKS to icon-only on scroll-down and expands back on scroll-up (it stays small
    # on a pause, until you scroll up). Reduced-motion drops the transitions — the nav only shrinks, never hides, so
    # it stays reachable. Desktop unaffected (pill is display:none).
    assert re.search(r"html:not\(\.scrolled\) header\s*\{[^}]*backdrop-filter:none", INDEX), \
        "the scroll-edge frost (clean header at the top) was removed"
    assert re.search(r"html\.nav-compact \.tabbar-inner\s*\{[^}]*height:44px", INDEX), \
        "the tab-bar shrink-on-scroll (compact height) was removed"
    assert re.search(r"html\.nav-compact \.tab span:not\(\.dm-dot\)\s*\{[^}]*max-height:0", INDEX), \
        "the compact nav must collapse the tab labels (icon-only on scroll-down)"
    assert 'classList.toggle("scrolled"' in INDEX and 'classList.add("nav-compact")' in INDEX \
        and 'classList.remove("nav-compact")' in INDEX, \
        "the scroll handler (frost + directional nav shrink/expand) was removed"
    assert re.search(r"prefers-reduced-motion: reduce\)\s*\{\s*\.tabbar-inner[^}]*transition:none", INDEX), \
        "under reduced motion the nav transitions must be dropped (nav stays reachable — it only shrinks)"


def test_history_has_a_readiness_heatmap():
    # FitTrackee-style calendar heatmap: a GitHub-style grid, one cell per day over the last N weeks, tinted
    # by that day's readiness state (--st). Rendered from the history data the screen already loads.
    assert 'id="history-heat"' in INDEX and "function renderHeat" in INDEX, "the readiness calendar heatmap was removed"
    assert re.search(r"\.heatgrid\s*\{[^}]*grid-auto-flow:column", INDEX), "the heatmap grid (GitHub-style columns) was removed"
    assert "renderHeat(historyItems)" in INDEX, "the heatmap must render from the history data"
    assert re.search(r"\.heat-cell\.on\s*\{[^}]*var\(--st\)", INDEX), "heat cells must tint by readiness state (--st)"


def test_history_rows_reveal_with_a_stagger():
    # History rows get a one-time staggered fade+rise entrance (crafted feel). fill:both -> a row can never
    # get stuck invisible; reduced-motion skips it entirely (no opacity:0 base).
    assert "@keyframes revealIn" in INDEX, "the list reveal keyframe was removed"
    assert re.search(r"prefers-reduced-motion: no-preference\)\s*\{\s*\.reveal-item\s*\{\s*animation: revealIn", INDEX), \
        "the reveal must be gated behind no-preference so reduced-motion never leaves a row invisible"
    assert "reveal-item readiness" in INDEX, "history rows must carry the staggered reveal class"


def test_loading_states_use_skeleton_shimmer():
    # Panels load with a shaped skeleton-shimmer placeholder (OSS/Bluesky pattern), not a bare "Loading…".
    # Reduced-motion-safe (the shimmer animation is disabled under prefers-reduced-motion).
    assert "@keyframes shimmer" in INDEX and re.search(r"\.sk::after\s*\{[^}]*animation:shimmer", INDEX), \
        "the skeleton shimmer was removed"
    assert re.search(r"prefers-reduced-motion: reduce\)\s*\{\s*\.sk::after\s*\{\s*animation:none", INDEX), \
        "the skeleton shimmer must be disabled under reduced motion"
    assert "function sk(" in INDEX, "the skeleton helper was removed"
    assert 'sk("card")' in INDEX and 'sk("rows")' in INDEX, "the dashboard/list loaders must use skeletons"
    assert 'class="muted">Loading…' not in INDEX, "no bare 'Loading…' placeholder should remain"


def test_premium_polish_grain_tabular_and_easing():
    # Tier-1 "optical detail" polish (applies to BOTH mobile + desktop): a filmic grain over the aurora (kills
    # gradient banding), tabular figures on the data numbers (never shift width), and one shared spring-ish
    # easing token. Cheap, high-perception, and none of it changes layout/behaviour.
    assert re.search(r"body::after\s*\{[^}]*feTurbulence", INDEX), "the aurora grain overlay was removed"
    assert re.search(r"body::after\s*\{[^}]*z-index:-1[^}]*pointer-events:none", INDEX), \
        "the grain must stay a backdrop layer (z-index:-1 + pointer-events:none) so it never touches content"
    assert "font-variant-numeric: tabular-nums" in INDEX, "tabular figures on the data numbers were removed"
    assert re.search(r"--ease:\s*cubic-bezier", INDEX), "the shared spring easing token (--ease) was removed"
    assert "-webkit-text-size-adjust:100%" in INDEX, "text-size-adjust (Dynamic Type stability) was removed"


def test_floating_nav_is_liquid_glass():
    # The bottom tab bar is the app's one glass surface (iOS 26 uses glass for the floating nav). It's upgraded
    # past a flat blur to the highest-fidelity web approximation: a light-refracting gradient RIM (::before),
    # a specular light-catch sheen (::after), and an active-tab glass capsule — all theme-tokened so light mode
    # softens the white specular instead of washing out. (True backdrop lensing is native-only; not faked.)
    assert ".tabbar-inner::before" in INDEX and ".tabbar-inner::after" in INDEX, "the glass rim/sheen layers were removed"
    for tok in ("--glass-fill", "--glass-rim", "--glass-spec"):
        assert INDEX.count(tok) >= 3, f"{tok} must be defined in :root + both light blocks (dark/forced-light/system-light)"
    assert "mask-composite: exclude" in INDEX, "the masked gradient rim (the refracting border) was removed"
    m = re.search(r"\.tab-indicator\s*\{[^}]*\}", INDEX)
    assert m and "linear-gradient" in m.group(0), "the selected-tab glass capsule (sliding indicator) must be a glass lozenge"
    # the Home FAB shares the same glass material as the pill (matching pair)
    assert re.search(r"\.ctx-back\s*\{[^}]*var\(--glass-fill\)", INDEX), "the Home FAB must use the same liquid-glass material as the nav pill"


def test_nav_selection_slides_and_drags():
    # WhatsApp-style: one indicator SLIDES to the active tab on tap, and can be DRAGGED between tabs with the
    # finger; tap-to-switch still works. Positions from live geometry; reduced-motion drops the slide transition.
    assert '.tab-indicator' in INDEX and 'ind.className = "tab-indicator off"' in INDEX, "the sliding selection indicator was removed"
    assert "window.tabIndicatorSync" in INDEX and "tabIndicatorSync()" in INDEX, "the tap-slide sync (from showScreen) was removed"
    assert re.search(r'inner\.addEventListener\("touchmove"', INDEX) and 'classList.add("dragging")' in INDEX, \
        "the drag handler (touchmove -> follow the finger) was removed"
    assert 'showScreen(near.dataset.screen)' in INDEX, "releasing a drag must snap to + activate the nearest tab"


def test_interactive_surfaces_have_a_mint_focus_ring():
    # Every keyboard-reachable surface that previously had no focus ring (buttons, forum posts, DM rows,
    # segment/checkbox labels, links) gets a consistent mint :focus-visible outline — the "visible keyboard
    # focus" quality floor. :focus-visible keeps it keyboard-only (no click-flicker regression).
    m = re.search(r"button:focus-visible[^{]*\{[^}]*\}", INDEX)
    assert m, "the shared focus-ring rule was removed"
    block = m.group(0)
    assert "outline:2px solid var(--accent)" in block, "the focus ring must be a 2px mint outline"
    for sel in (".post:focus-visible", ".dm-row:focus-visible", ".seg:has(:focus-visible)", "a:focus-visible"):
        assert sel in block, f"{sel} lost its keyboard focus ring"


def test_hero_readiness_score_counts_up():
    # The hero readiness number rises 0->N with the orb-ring sweep (Whoop/Oura open animation). One number,
    # the hero; must snap under reduced-motion and leave the "—" empty state untouched.
    assert "function countUpScore" in INDEX, "the hero-score count-up was removed"
    assert "countUpScore(el)" in INDEX, "the hero-score count-up is never called from the render"
    m = re.search(r"function countUpScore\(el\)\s*\{.*?\n    \}", INDEX, flags=re.S)
    assert m, "countUpScore body not found"
    body = m.group(0)
    assert "reducedMotion()" in body, "the hero-score count-up must snap under reduced motion"
    assert "Number.isFinite" in body, "the hero-score count-up must bail on the non-numeric '—' state"


def test_profile_is_grouped_into_four_cards():
    # Profile was 6 floating cards; regrouped iOS-Settings-style into 4 (You / Preferences / Account /
    # Danger) with .sep hairlines between sub-sections. Each sub-section keeps its icon eyebrow (h2), so
    # all 6 headings survive — only the card containers merged. Guards the grouping, not pixels.
    m = re.search(r'<section id="screen-profile".*?</section>', INDEX, flags=re.S)
    assert m, "the profile screen section vanished"
    prof = m.group(0)
    assert prof.count('<div class="card') == 4, "profile must be exactly 4 grouped cards (You/Preferences/Account/Danger)"
    assert prof.count("<h2>") == 6, "all six section eyebrows must survive the merge"
    # engagement is merged INTO the profile card (a .sep, not a new card, sits between Save profile and it)
    assert re.search(r"Save profile.*?<hr class=\"sep\">.*?Community engagement", prof, flags=re.S), \
        "Community engagement must share the 'You' card with the profile form (divided by a .sep)"
    # privacy is merged INTO the preferences card with the theme control
    assert re.search(r"Display &amp; accessibility.*?<hr class=\"sep\">.*?Privacy &amp; data", prof, flags=re.S), \
        "Privacy & data must share the 'Preferences' card with Display & accessibility (divided by a .sep)"


def test_forum_rows_carry_generative_avatars():
    # Forum reuses the same deterministic avatar system as DMs (avatarHtml) so a person looks the same
    # everywhere — on the list byline, the open post's author line, and every comment. Not new decoration:
    # the exact helper the messages surface already uses.
    assert "avatarHtml(p.author, 20)" in INDEX, "the forum list byline must show the author's generative avatar"
    assert "avatarHtml(p.author, 26)" in INDEX, "the open post's author line must show the author's avatar"
    assert "avatarHtml(c.author, 28)" in INDEX, "each comment must show its author's avatar"
    assert 'class="muted byline"' in INDEX, "the list byline wrapper (flex-aligned avatar + text) was removed"
    m = re.search(r"\.byline\s*\{[^}]*\}", INDEX)
    assert m and "display:flex" in m.group(0), "the byline must be flex so the avatar aligns with the text"


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


def test_dashboard_prompts_a_checkin_instead_of_faking_an_ai_outage():
    # With a profile but no check-in there are no metrics to score, so the dashboard returns
    # needs_checkin (not ai_status 'unavailable'). The UI must render the check-in prompt for that
    # state, NOT the "AI service down" warning — otherwise a brand-new user sees a false outage.
    assert "d.needs_checkin" in INDEX, "the dashboard must handle the needs_checkin state"
    assert re.search(r"needs_checkin[\s\S]{0,400}Log today", INDEX), \
        "the needs_checkin branch must prompt the first check-in"


def test_home_fab_shrinks_bottom_anchored_to_track_the_nav():
    # The compact (scrolled) nav shrinks bottom-anchored to 44px; the Home FAB must shrink the same way
    # (width/height to 44px), NOT transform: scale() around its centre — a centre-scaled FAB keeps its
    # midpoint fixed while the nav's drops, so they visibly misalign on scroll (the 2026-07-13 report).
    m = re.search(r"html\.nav-compact \.ctx-back\s*\{([^}]*)\}", INDEX)
    assert m, "the compact-nav rule for the Home FAB (.ctx-back) is missing"
    assert "width:44px" in m.group(1) and "height:44px" in m.group(1), \
        "the compact Home FAB must shrink to 44px (bottom-anchored), matching the compact nav height"
    assert "scale(" not in m.group(1), \
        "the compact Home FAB must not centre-scale (that misaligns it with the bottom-anchored nav)"
