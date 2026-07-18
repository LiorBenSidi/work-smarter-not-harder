"""Frontend shell test — GET / serves the single-page app with its API hooks. OWNER: Lior.

JS behaviour itself needs a browser (exercised by the running stack / system tests); this pins that
the page is served and wired to every endpoint, so a template break is caught in CI.
"""
import re


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
    # timestamp is now shown as a relative time, still escaped: escapeHtml(timeAgoStr(it.timestamp))
    assert "escapeHtml(timeAgoStr(it.timestamp))" in html
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
    # loadConversations/renderThread/dmReply/syncEmailConsent + openMessages/activity-read).
    assert html.count('sessionChanged(u, "') >= 10
    assert 'sessionChanged(u, "openMessages")' in html and 'sessionChanged(u, "activity-read")' in html
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


def test_checkin_scales_and_live_validation_are_wired(client):
    # The 1–10/0–10 fields are colour-coded tap scales backed by a hidden input (same POST body); the two
    # typed fields validate live, and Submit stays greyed (aria-disabled) until every field is valid.
    html = client.get("/").get_data(as_text=True)
    for field in ["fatigue", "soreness", "training_load"]:
        assert f'data-field="{field}"' in html                     # the scale builds from this
        assert f'type="hidden" id="{field}"' in html               # hidden input carries the chosen value
    assert "function buildScales(" in html and "function validateCheckin(" in html
    assert "function updateCheckinValidity(" in html
    assert 'button type="submit" class="block" aria-disabled="true"' in html   # greyed until valid
    assert 'class="field-err" data-for="sleep_hours"' in html      # live per-field error
    assert 'class="field-err" data-for="resting_hr"' in html


def test_checkin_saved_flash_auto_dismisses(client):
    # #355: the "Check-in saved." success is a TRANSIENT toast — it auto-clears after a few seconds so it can't
    # linger on the Today screen or reappear when the user navigates back to it. Errors are NOT auto-cleared.
    html = client.get("/").get_data(as_text=True)
    assert "function checkinFlashOk(msg)" in html                              # the auto-dismiss helper
    assert 'setTimeout(() => flash("checkin-flash", "", "ok"), 4000)' in html  # ...clears the flash after a few seconds
    assert 'checkinFlashOk("Check-in saved.")' in html                         # the success path uses it
    assert 'flash("checkin-flash", "Check-in saved."' not in html              # the old lingering (never-cleared) flash is gone


def test_filter_sort_chips_keep_newest_on_the_row(client):
    # #353: on a narrow screen the "↓ Newest" sort chip must stay on the filters' row, not wrap to a line of its
    # own. The filters/sorts wrap inside a .chip-group; the ".dir" sort chip is its SIBLING, pinned top-right.
    html = client.get("/").get_data(as_text=True)
    assert "#history-filters, #forum-sorts { flex-wrap:nowrap;" in html        # the row itself never wraps
    assert "#history-filters .chip-group, #forum-sorts .chip-group" in html    # the chips wrap inside their group
    assert '<div class="chip-group">' in html                                  # the group wraps the filter/sort chips
    assert 'id="history-dir" class="chip dir"' in html and 'id="forum-dir" class="chip dir"' in html  # sort chip stays a sibling


def test_slack_inspired_polish_present(client):
    # Slack-style polish: an unread COUNT on the Chat nav (not just a dot), a recent-chats avatar strip,
    # and a frosted backdrop behind the open account menu.
    html = client.get("/").get_data(as_text=True)
    assert 'id="dm-avatar-strip"' in html and "function renderAvatarStrip(" in html   # recent-chats avatar row
    assert 'id="menu-backdrop"' in html and 'class="menu-backdrop"' in html            # menu frost element
    assert "bd.hidden = false" in html and "bd.hidden = true" in html                  # backdrop toggled with the menu
    assert "d.textContent = n > 0 ? label" in html                                     # the nav badge shows a count, not just a dot


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


def test_service_worker_is_stamped_with_a_build_version(client):
    # The __BUILD__ placeholder must be replaced at serve time so every deploy ships a worker with a new
    # cache name -> the installed PWA auto-updates. If the raw literal leaked through, no release would.
    sw = client.get("/sw.js").get_data(as_text=True)
    assert "__BUILD__" not in sw, "the build placeholder was served unstamped (auto-update won't trigger)"
    assert re.search(r'CACHE\s*=\s*"ws-shell-[0-9a-f]{8}"', sw), "SW cache name must carry the build hash"


def test_index_registers_the_auto_update_loop(client):
    # The home-screen app refreshes itself: it listens for a new worker taking control and re-checks on
    # foreground. Pin both so the auto-update behavior can't be silently dropped.
    html = client.get("/").get_data(as_text=True)
    assert "controllerchange" in html, "the reload-on-new-worker hook was removed (no auto-update)"
    assert "reg.update()" in html, "the foreground update check was removed (backgrounded PWA won't refresh)"


def test_hero_display_font_is_actually_served(client):
    # The guard test asserts the wiring STRINGS exist; this proves Flask really serves the font bytes, so a
    # font missing from the image or a mis-set static route is caught in CI, not at the demo (fallback font).
    resp = client.get("/static/fonts/bricolage-800-latin-v1.woff2")
    assert resp.status_code == 200, "the self-hosted display font 404s — hero would fall back to system font"
    assert resp.get_data()[:4] == b"wOF2", "served bytes are not a valid woff2 font"


def test_account_menu_present_and_wired(client):
    # Wolt-style corner account menu: an avatar button in the header opens a dropdown with the identity
    # block + quick actions (Profile / Theme / Log out). The menu is an accessible popup (aria-haspopup
    # + aria-expanded + aria-controls), and its logout routes through the shared doLogout.
    html = client.get("/").get_data(as_text=True)
    assert 'id="user-menu-btn"' in html and 'id="user-menu-panel"' in html
    assert 'aria-haspopup="menu"' in html and 'aria-controls="user-menu-panel"' in html
    assert 'data-act="profile"' in html and 'data-act="logout"' in html
    assert "function doLogout(" in html and "closeUserMenu()" in html   # one logout path, shared with the Profile button


def test_theme_change_has_a_single_source_of_truth(client):
    # the corner menu's theme segments and the Profile radios must both route through setTheme, so the two
    # controls can never drift out of sync (setTheme persists, applies, and mirrors every control).
    html = client.get("/").get_data(as_text=True)
    assert "function setTheme(" in html and "function syncThemeControls(" in html
    assert 'class="um-seg"' in html and 'data-theme="system"' in html and 'data-theme="dark"' in html
    assert "#user-menu-panel .um-seg" in html   # syncThemeControls mirrors the choice onto the menu segments


def test_profile_lives_in_the_corner_menu_not_a_bottom_tab(client):
    # Design decision: Profile/account is reached ONLY via the corner account menu (the Wolt pattern),
    # not via a redundant bottom-nav tab. The bottom tab bar is the 4 frequent sections; the corner
    # avatar owns identity + account. Guards against the two-Profiles redundancy creeping back.
    html = client.get("/").get_data(as_text=True)
    assert 'data-screen="profile"' not in html          # no bottom-nav Profile tab
    assert 'data-act="profile"' in html                 # the corner menu is the single Profile entry
    assert 'showScreen("profile")' in html              # ...and it still routes to the Profile screen
    for screen in ("history", "forum", "messages"):
        assert f'data-screen="{screen}"' in html        # the frequent section tabs remain
    assert 'data-screen="today"' not in html            # Today is the Home button now, not a tab


def test_checkin_streak_badge_present_and_wired(client):
    # A consecutive-day streak badge on Today (Wolt's tenure footer -> fitness motivation), computed on
    # the client from the loaded history and rendered whenever history loads (login + after a check-in).
    html = client.get("/").get_data(as_text=True)
    assert 'id="streak-badge"' in html
    assert "function computeStreak(" in html and "function renderStreak(" in html
    assert "renderStreak(items)" in html                 # driven from loadHistory -> updates after each check-in
    assert "-day streak" in html                         # the badge copy


def test_checkin_due_capsule_present_and_wired(client):
    # Wolt's 'shown-only-when-relevant' capsule: a floating nudge that appears ONLY when today's check-in
    # is missing AND you're not already on Today (where the form lives). Tapping it jumps to the form.
    html = client.get("/").get_data(as_text=True)
    assert 'id="checkin-capsule"' in html
    assert "function updateCheckinCapsule(" in html
    assert 'checkinDue && currentScreen !== "today"' in html   # the two-part relevance gate
    assert "checkinDue = streak.hasHistory && !streak.loggedToday" in html   # driven from the streak/history
    assert 'showScreen("today")' in html and "scrollIntoView" in html        # tap -> Today + the check-in form


def test_responsive_dual_nav_present(client):
    # Dedicated desktop + mobile layouts from ONE responsive codebase: a desktop top-nav in the header
    # (shown only when signed in, >=860px) AND a mobile floating bottom-pill bar (<860px). Both drive the
    # same showScreen via [data-screen], so Safari 'Request Desktop' (a wide viewport) lands on the desktop layout.
    html = client.get("/").get_data(as_text=True)
    assert 'id="topnav"' in html and 'class="topnav"' in html      # the desktop top-nav
    assert 'class="tabbar"' in html                                # the mobile bottom bar still exists
    for screen in ("history", "forum", "messages"):
        assert html.count(f'data-screen="{screen}"') >= 2          # each section in BOTH navs (mobile pill + desktop top-nav)
    assert html.count('data-screen="today"') == 0                  # Today dropped -> Home reached via the FAB (mobile) / logo + Home button (desktop)
    assert "@media (min-width: 860px)" in html                     # the desktop breakpoint (the Request-Desktop switch)
    assert "max-width:920px" in html                               # wider desktop content
    assert 'document.querySelectorAll("[data-screen]")' in html    # showScreen + clicks drive both navs
    assert "function setDmDot(" in html                            # the Chat unread pulse toggles on both navs
    assert ".topnav.nav-on" in html                                # top-nav appears only when signed in


def test_desktop_home_button_present_and_wired(client):
    # Desktop mirror of the mobile Home FAB: a Home button in the top nav (left of History) that appears only
    # off-Today and routes to Today. Wired DIRECTLY (not via data-screen), so Today stays out of the tab model
    # (the dual-nav invariant above still holds).
    html = client.get("/").get_data(as_text=True)
    assert 'id="nav-home"' in html and 'class="navlink nav-home"' in html
    assert 'data-screen' not in html.split('id="nav-home"')[1].split(">")[0]   # NOT a data-screen tab
    assert '$("nav-home").addEventListener("click", () => showScreen("today"))' in html
    assert "navHome.hidden = !offHome" in html                     # shown only off-Today, like the mobile FAB


def test_home_fab_is_always_a_home_button(client):
    # Wolt's 'home button only when not home': the FAB is shown off-Today, hidden on Today. It is ALWAYS a
    # Home icon (a back chevron there read as confusing) and ALWAYS goes to Today; the drill-in "back" lives
    # on the in-view close (the ✕ in a post / the ← Back in a DM thread), not on this button.
    html = client.get("/").get_data(as_text=True)
    assert 'id="ctx-back"' in html and "function updateCtxBack(" in html
    assert 'const offHome = currentScreen !== "today"' in html               # shown iff off-Today
    assert "CTX_HOME_ICON" in html and "CTX_BACK_ICON" not in html           # always a Home icon, never a back chevron
    assert '$("ctx-back").addEventListener("click", () => showScreen("today"))' in html   # always goes to Today
    assert "ctxBackTarget" not in html                             # the old drill-in target logic is gone


def test_desktop_logo_is_the_home_button(client):
    # Desktop fix: the separate Home/Back button is HIDDEN on desktop (it shifted the whole header). Instead
    # the LOGO becomes the home button off-Today — a home icon appears inside the brand dot + clicking the
    # brand goes to Today in-app (no reload). The header is flagged .off-home to drive it. Mobile keeps ctx-back.
    html = client.get("/").get_data(as_text=True)
    assert 'class="brand-home-ico"' in html                        # the home icon lives inside the brand dot
    assert "header.off-home .brand-home-ico" in html               # shown on desktop when off-Today
    assert '.ctx-back { display:none; }' in html                   # ...and the separate button is gone on desktop
    assert 'const offHome = currentScreen !== "today"' in html     # off-Today drives both the FAB and the logo home-icon
    assert 'classList.toggle("off-home", offHome)' in html         # header flagged off-Today
    assert "if (currentUser) { e.preventDefault(); showScreen" in html         # the logo is an in-app home link


def test_mobile_nav_pill_is_translucent_and_ios_frosted(client):
    # The mobile floating pill must be see-through (content shows behind it), not an opaque slab, AND ship the
    # -webkit- prefix so the frosted blur applies on iOS Safari. It's now an iOS-26 liquid-glass material: a
    # translucent --glass-fill (a real alpha), an upgraded blur+saturate+brightness, and the rim/sheen layers.
    html = client.get("/").get_data(as_text=True)
    assert "background: linear-gradient(180deg, var(--glass-fill)" in html      # translucent glass fill (real alpha token)
    assert "--glass-fill: rgba(255,255,255,.12)" in html                        # the fill IS translucent (not an opaque slab)
    assert "var(--card) 90%, var(--bg)" not in html                            # NOT the old opaque background
    assert html.count("-webkit-backdrop-filter") >= 2                          # the pill AND the FAB frost on iOS
    assert "backdrop-filter: blur(26px) saturate(1.9) brightness(1.12)" in html  # upgraded liquid-glass frost


def test_mobile_nav_pill_is_centered_stable_with_an_aligned_fab(client):
    # Wolt's mobile layout: a compact pill that stays CENTERED in a full-width rail and NEVER shifts, plus a
    # bottom-left Home FAB the SAME 56px height as the pill (both bottom:12) so they're vertically centered on
    # one line. The FAB appearing/disappearing must not move the pill.
    html = client.get("/").get_data(as_text=True)
    assert ".ctx-back { position:fixed; left:12px;" in html                    # bottom-left floating FAB
    assert "width:56px; height:56px" in html                                   # FAB is 56px == the pill height (aligned)
    assert "gap:4px; height:56px; padding:6px" in html                         # the pill's fixed 56px height
    assert "width: min(clamp(176px, 55vw, 216px), calc(100vw - 152px))" in html  # compact + capped so it never overlaps the FAB
    assert "justify-content:center" in html                                    # the pill is centered in its rail
    assert "has-ctx" not in html                                               # NO sideways shift — the pill is stable


def test_today_screen_is_a_region_not_an_orphaned_tabpanel(client):
    # a11y: Today is now reached via the Home button (mobile) / logo (desktop), NOT a tab. Its screen must be
    # a `region` (like Profile), not a `tabpanel` with no controlling tab — which violates the WAI-ARIA tabs
    # pattern (a tablist whose panel has no tab, and no selected tab on the Today view).
    html = client.get("/").get_data(as_text=True)
    assert 'id="screen-today" class="screen" role="region"' in html
    assert 'id="screen-today" class="screen" role="tabpanel"' not in html


def test_filter_sort_chips_present_and_wired(client):
    # Wolt-style filter chips: History filters by readiness (All/Ready/Moderate/Rest); Forum sorts
    # (Recent/Top/Mine). Client-side over the cached list; the active chip is highlighted.
    html = client.get("/").get_data(as_text=True)
    assert 'id="history-filters"' in html and 'id="forum-sorts"' in html
    for f in ('data-filter="all"', 'data-filter="ready"', 'data-filter="moderate"', 'data-filter="rest"'):
        assert f in html
    for s in ('data-sort="recent"', 'data-sort="top"', 'data-sort="mine"'):
        assert s in html
    assert "function renderHistoryList(" in html and "function renderForumList(" in html
    assert "historyFilter" in html and "forumSort" in html         # the filter/sort state drives the render


def test_dm_reopen_repaints_even_when_the_thread_is_unchanged(client):
    # Regression (live bug, 2026-07-15): openThread resets #dm-thread to skeletons with a direct innerHTML=,
    # which leaves setHtmlIfChanged's per-node __lastHtml cache stale. Re-opening an UNCHANGED thread then
    # made renderThread compute identical HTML, hit the cache, skip the repaint, and leave the skeletons up
    # (the thread rendered the FIRST time it was opened and was blank every time after). openThread must
    # invalidate that cache when it stomps the DOM, so renderThread always repaints on open.
    html = client.get("/").get_data(as_text=True)
    start = html.index("async function openThread(")
    body = html[start:html.index("async function renderThread(", start)]   # the openThread function body
    assert "__lastHtml" in body and "undefined" in body, \
        "openThread must clear the setHtmlIfChanged __lastHtml cache when it resets #dm-thread to skeletons"


def test_open_dm_thread_is_a_pinned_single_scroll_chat_pane(client):
    # UX fix (2026-07-15): an open DM thread must be a fixed-height chat pane — the header (Back + peer) and
    # the composer stay PINNED and the message list is the ONLY scroll (no page-scroll AND inner-scroll, and
    # the Back button never scrolls away). Scoped to #dm-thread-view; toggled via a `thread-open` class.
    html = client.get("/").get_data(as_text=True)
    assert "#dm-thread-view > .card" in html and "flex-direction:column" in html      # the flex chat pane
    assert "#dm-thread-view .dm-thread { flex:1 1 auto; max-height:none; }" in html    # the message list is the single scroll
    assert "#screen-messages.thread-open .screen-head { display:none; }" in html       # redundant title hidden while in a thread
    assert 'classList.add("thread-open")' in html and 'classList.remove("thread-open")' in html   # toggled on open/close


def test_dm_pane_is_pinned_between_header_and_nav(client):
    # #351/#352: the open DM pane is PINNED (position:fixed) between the sticky header and the floating nav,
    # anchored to their RUNTIME-MEASURED positions (sizeDmThreadPane) — never a hard-coded viewport guess.
    # Fixed => out of page flow, so page-scroll can't slide the Back button under the header (#351); its bottom
    # is anchored just above the nav, so the pane fills the space with no dead gap (#352). Live-verified on the
    # Docker stack at a mobile viewport: page overflow 0, forced scroll 0, Back never moves, gap-to-nav 12px.
    html = client.get("/").get_data(as_text=True)
    assert "position:fixed; left:50%; transform:translateX(-50%)" in html      # the pane is pinned to the viewport
    assert "top:var(--dm-pane-top" in html and "bottom:var(--dm-pane-bottom" in html   # anchored to measured header/nav
    assert "function sizeDmThreadPane()" in html                               # the runtime sizer exists
    assert 'setProperty("--dm-pane-top"' in html and 'setProperty("--dm-pane-bottom"' in html
    assert "sizeDmThreadPane();" in html                                       # called on thread open
    assert "addEventListener(e, sizeDmThreadPane)" in html                     # re-measured on resize / orientationchange


def test_checkin_capsule_hidden_over_an_open_dm_thread(client):
    # #352 follow-up (found in live testing): the "check-in due" capsule floats above the nav and used to sit
    # ON TOP of an open DM thread's composer. It must hide while a thread is open (you can't check in from a
    # thread) and return on close. open/closeThread re-evaluate it.
    html = client.get("/").get_data(as_text=True)
    assert 'const threadOpen = $("dm-thread-view") && !$("dm-thread-view").hidden;' in html
    assert 'el.hidden = !(checkinDue && currentScreen !== "today") || threadOpen;' in html
    assert html.count("updateCheckinCapsule();") >= 3          # showScreen + openThread + closeThread (at least)


def test_dm_thread_pages_older_history_on_demand(client):
    # #331 (client half): the thread read is bounded server-side to the newest page (MESSAGE_PAGE_DEFAULT=50),
    # so the client must ACCUMULATE pages and let the reader fetch older history — otherwise a >50-message thread
    # is silently truncated with no way back. The thread keeps a deduped, oldest-first union (dmMsgs) and pages
    # strictly BEFORE its oldest message (created_at cursor), prepending without yanking the scroll position.
    html = client.get("/").get_data(as_text=True)
    assert "let dmMsgs = []" in html and "dmOldestCursor" in html and "dmMoreOlder" in html   # the accumulator + cursor + gate exist
    assert "function mergeDmMsgs(page)" in html                                                # newest/older pages fold in, deduped by id
    assert "byId.set(m.id, m)" in html                                                         # dedup keyed on the stable message id
    assert "async function loadEarlierDm()" in html and 'onclick="loadEarlierDm()"' in html    # the control is defined AND wired
    assert '"?before=" + encodeURIComponent(dmOldestCursor)' in html                           # it pages before the oldest held message
    assert "dmOldestCursor = dmMsgs[0].created_at" in html                                      # cursor advances to the new oldest (monotonic -> no loop)
    assert "if (older.length < DM_PAGE) dmMoreOlder = false" in html                            # a short page retires the control (start reached)
    assert "box.scrollTop = prevTop + (box.scrollHeight - prevHeight)" in html                  # prepend holds the reader's place
    assert "if (dmLoadingOlder || !dmMoreOlder || dmOldestCursor === null) return" in html      # re-entrancy / no-op guards


def test_screen_switch_has_a_subtle_crossfade(client):
    # #356: switching screens replays a subtle entrance on the incoming .screen (a hidden->visible toggle alone
    # does NOT restart a CSS animation, so switches snapped). It re-triggers the animation on the SCREEN element
    # only — never re-mounting content (the prior "jumpy flicker" came from tearing down content nodes) — and
    # no-ops under reduced motion (the reducedMotion() guard + the global prefers-reduced-motion rule).
    html = client.get("/").get_data(as_text=True)
    assert "@keyframes screenSwap" in html                                 # the cross-fade keyframe exists
    assert '_screen.style.animation = "screenSwap' in html                 # it's applied to the incoming screen
    assert "void _screen.offsetWidth" in html                              # the reflow that actually restarts the animation
    assert "if (_screen && !reducedMotion())" in html                      # opt-out honored (no reflow/anim under reduced motion)


def test_history_detail_view_is_wired(client):
    # #354: tapping a History row or a heatmap cell opens a detail modal showing that check-in's inputs, readiness
    # + per-state confidence, calories, and recommendations. The modal is BODY-level (a fixed child of a hidden
    # .screen wouldn't paint); rows/cells are keyboard-accessible; recommendations degrade for pre-#354 entries.
    html = client.get("/").get_data(as_text=True)
    assert 'id="history-detail"' in html and 'id="hdetail-body"' in html          # the modal shell exists
    assert "function openHistoryDetail(entry)" in html                            # populated from the in-memory entry
    assert 'data-ts="' in html and 'aria-label="View this check-in' in html        # rows carry their entry + are labeled buttons
    assert 'data-day="' in html                                                   # heatmap cells (with a check-in) are tappable
    assert '"hd-recs"' in html                                                    # the recommendations list renders
    assert "for this check-in." in html                                          # graceful fallback copy for missing recs
    assert 'e.key === "Escape"' in html                                          # ESC closes the modal


def test_enter_drops_a_line_in_chat_forum_and_comments(client):
    # UX (2026-07-15): Enter must insert a newline (line drop), not send/post, in the chat reply, forum post
    # body, and comments. The DM reply textarea sends only on Shift+Enter (plain Enter = newline); every
    # composer body is a <textarea> (a textarea never submits its form on Enter), including the comment field
    # which used to be a single-line <input> (Enter submitted it). Login + regular single-line forms keep the
    # default Enter=submit (they were never touched).
    html = client.get("/").get_data(as_text=True)
    assert 'e.shiftKey) { e.preventDefault(); $("dm-reply-form").requestSubmit()' in html                 # chat sends on Shift+Enter
    assert '&& !e.shiftKey) { e.preventDefault(); $("dm-reply-form")' not in html                         # the old send-on-plain-Enter is gone
    assert '<textarea name="body" placeholder="Add a comment"' in html                                    # comment is a textarea now
    assert '<input name="body"' not in html                                                               # no single-line body input remains (would submit on Enter)


def test_mutations_and_uploads_surface_their_failures(client):
    # Robustness (2026-07-15): a failed action must never look like a success. Four sites used to swallow
    # errors — deletePost / editPost-save had no else branch (a 429/network drop = a click that did nothing),
    # and the forum-post + DM-reply attachment paths flashed "Posted."/cleared the flash even when every
    # upload failed (the text landed, the photo vanished silently). Each now surfaces the failure.
    html = client.get("/").get_data(as_text=True)
    # deletePost: an in-flight guard (no false error on a double-click) + a failure flash.
    dp = html[html.index("async function deletePost("):html.index("function editPost(")]
    assert "deleteInFlight" in dp                                                   # guards the double-click 404
    assert 'flash("forum-flash"' in dp and "Couldn't delete" in dp                  # failure is surfaced
    # editPost save: a failure flash on a bad PATCH.
    ep = html[html.index("function editPost("):html.index("function cancelEdit(")]
    assert "Couldn't save your changes" in ep and 'flash("forum-flash"' in ep
    # forum-post upload: a dropped attachment downgrades the clean "Posted." to a warning.
    assert "couldn't be attached." in html                                         # the attachment-failure copy exists
    assert 'attachWarn ? "warn" : "ok"' in html                                    # forum + DM both branch the flash kind on the warn
    # DM reply: a dropped attachment must not clear the flash to a silent success.
    dm = html[html.index('onSubmit("dm-reply-form"'):html.index('$("dm-files").addEventListener')]
    assert "attachWarn" in dm and 'flash("dm-reply-flash", attachWarn' in dm


def test_forum_realtime_sse_is_wired_on_the_client(client):
    # Real-time forum (2026-07-15): the client subscribes to the SSE `forum` push and, ONLY on the forum
    # screen, refreshes the list + the open post's detail — but never over a draft (a focused/non-empty
    # comment or edit body is preserved, so a teammate's live change can't wipe what the user is typing).
    html = client.get("/").get_data(as_text=True)
    assert 'addEventListener("forum", onForumEvent)' in html            # subscribed to the forum push
    assert "function onForumEvent()" in html
    body = html[html.index("function onForumEvent()"):html.index("function startEvents()")]
    assert 'currentScreen !== "forum"' in body                                  # scoped to the forum screen
    assert "loadForum({ quiet: true })" in body                                 # ...refreshed IN PLACE (no skeleton flash)
    assert "openPost(currentPostId)" in body                                    # refreshes the open post
    assert "document.activeElement" in body and ".value.trim()" in body         # ...but not over a live draft
    # If the OPEN post was deleted live, close it with an accurate note — NOT re-fetch it (a 404 -> the
    # generic "couldn't open, try again", which is misleading when the post is simply gone).
    assert "forumPosts.some((p) => p.id === currentPostId)" in body             # detect the open post vanished
    assert "This post was removed." in body                                     # accurate copy for a live delete
    # loadForum must actually honour the quiet flag (skip the skeleton) — else the guard above is cosmetic.
    lf = html[html.index("async function loadForum("):html.index("function renderForumList()")]
    assert "opts && opts.quiet" in lf and 'sk("rows")' in lf                    # quiet -> no skeleton paint


def test_forum_realtime_has_a_self_healing_poll_backstop(client):
    # Robustness (2026-07-15): EventSource auto-reconnects a dropped stream, but a FATAL error leaves it
    # CLOSED (readyState 2) with no retries — after which real-time silently dies. Unlike DM/notify, the
    # forum had no other backstop. The 45s poll (a) restarts a CLOSED stream and (b) re-syncs the forum list.
    #
    # #342 STRENGTHENED the (b) half. It used to re-sync only while `evtSource.readyState !== 1` — i.e. it
    # trusted an OPEN stream to mean "pushes are working". That is false, provably: a stream whose forum-rev
    # read failed once went silent for its whole life while staying OPEN (see the recovery tests in
    # test_messages.py), and a rev bump landing in the reconnect gap is absorbed by the next stream's baseline
    # and never sent. readyState describes the CONNECTION, never the push path — so the gate is now simply
    # "is the user looking at the forum", which bounds staleness at one tick however a push goes missing.
    html = client.get("/").get_data(as_text=True)
    assert "function pollBackstop()" in html
    assert "setInterval(pollBackstop, 45000)" in html                        # the SSE backstop runs it
    assert "setInterval(pollBackstop, 15000)" in html                        # the no-SSE fallback runs it too
    body = html[html.index("function pollBackstop()"):html.index("function startEvents()")]
    assert "evtSource.readyState === 2" in body and "startEvents()" in body  # a CLOSED stream is restarted
    assert 'currentScreen === "forum"' in body                               # the forum re-syncs on its screen
    # The re-sync must NOT be gated on the stream merely looking healthy — that was the #342 defect.
    assert "readyState !== 1" not in body, "the forum re-sync must not treat an OPEN stream as proof of pushes"
    # It goes through onForumEvent, NOT a bare loadForum: onForumEvent also closes an open post that has
    # vanished ("This post was removed."). A missed DELETE is exactly what this backstop catches, and a bare
    # loadForum would leave that detail orphaned on screen. (Assert the CALL, not the mere absence of the
    # word — "loadForum" legitimately appears in this function's comments.)
    assert "!forumPaged && !typingHere) onForumEvent();" in body
    # ...and it MUST skip in two cases, or the timer harms the user it is meant to help:
    assert "!forumPaged" in body        # loadForum restarts at page 1 -> a re-sync would wipe older pages
    assert "contains(document.activeElement)" in body   # stashDetail re-parents -> blurs a reply being typed
    assert "pollNotifications()" in body                                     # DM/notify catch-up preserved
    # ...and the restart must NOT early-return before the forum catch-up — else changes made DURING the outage
    # (already in the restarted stream's baseline, so never pushed) would leave the feed stale until a manual load.
    assert "startEvents(); return" not in body


def test_history_rows_show_the_real_readiness_score_not_the_band_level(client):
    # issue #1: History used to show the band LEVEL (readinessClass -> 100/66/33). It now shows the SAME
    # 0-100 score the dashboard computes, from each entry's stored proba (band-centre fallback for old
    # entries with no proba) — so the dashboard's 84 and History agree instead of showing 84 vs 100.
    html = client.get("/").get_data(as_text=True)
    render = html[html.index("function renderHistoryList()"):html.index("function updateHistoryDirLabel()")]
    assert "readinessScore({ state: it.assessment, proba: it.proba })" in render   # real score from stored proba
    assert 'class="hrow-score">\' + score' in render                               # ...is what the row prints
    assert "] = readinessClass(it.assessment)" in render                           # class still drives the colour
    assert "+ pct +" not in render                                                 # the old band-level number is gone


def test_history_has_a_sort_direction_toggle_defaulting_newest_first(client):
    # UX (2026-07-15): History gained a Forum-style asc/desc toggle, defaulting to newest-on-top. The sort
    # is display-only (a .slice() copy) so the trend/heatmap/streak keep their stored chronological order.
    html = client.get("/").get_data(as_text=True)
    assert 'id="history-dir"' in html                                           # the toggle exists in the filter row
    assert 'historyDir = "desc"' in html                                        # default = newest first
    render = html[html.index("function renderHistoryList()"):html.index("function updateHistoryDirLabel()")]
    assert "items.slice().sort(" in render and "historyDir" in render           # display list is sorted (on a copy)
    assert "localeCompare" in render and ".timestamp" in render                 # ...by timestamp
    # the toggle flips direction and re-renders; filter chips stay scoped to [data-filter]
    assert 'chip.id === "history-dir"' in html                                  # the toggle branch is wired
    assert 'querySelectorAll(".chip[data-filter]")' in html                     # dir button isn't toggled "active"


def test_checkin_submit_frees_the_form_on_save_not_after_the_refresh(client):
    # #6: the Submit button is disabled only while the /checkin POST is in flight. The AI-backed dashboard
    # reload runs in the BACKGROUND (un-awaited), so a slow/backed-up /predict can't leave Submit stuck-grey
    # with the values still selected. On save we reset + re-enable immediately; the refresh + count-up follow.
    html = client.get("/").get_data(as_text=True)
    start = html.index('onSubmit("checkin-form"')
    handler = html[start:start + 2800]                                            # the check-in submit handler body
    assert '"Saving…"' in handler                                                 # in-flight feedback
    assert "await Promise.all([loadDashboard" not in handler                      # the refresh is NOT awaited
    assert "Promise.all([loadDashboard({ fresh: true }), loadHistory()]).then(countUpKcal)" in handler  # ...it's backgrounded
    assert 'f.reset(); resetCheckinScales(); updateCheckinValidity();' in handler  # form reset on save


def test_reset_link_survives_a_service_worker_reload(client):
    # #3: the reset email link opened the reset form but a service-worker auto-reload (a new build claims the
    # page) then dropped it to login, because the token was scrubbed from the URL. Now the token is stashed in
    # sessionStorage so it survives exactly one reload, and is consumed on restore so it can't trap the user.
    html = client.get("/").get_data(as_text=True)
    init = html[html.index("async function init()"):html.index("async function init()") + 1400]
    assert 'sessionStorage.setItem("pending_reset_token"' in init                 # stashed before the URL is scrubbed
    assert 'sessionStorage.getItem("pending_reset_token")' in init                # recovered after a reload
    assert 'sessionStorage.removeItem("pending_reset_token")' in init             # ...and consumed (survives ONE reload, no trap)
    assert 'sessionStorage.removeItem("pending_reset_token")' in html[html.index('onSubmit("reset-form"'):html.index('onSubmit("reset-form"') + 500]  # cleared on success


def test_history_heatmap_is_seven_weeks(client):
    # The readiness heatmap is a 7x7 square (7 weeks x 7 days), driven by the single WEEKS constant.
    html = client.get("/").get_data(as_text=True)
    render = html[html.index("function renderHeat("):html.index("function renderHeat(") + 1600]
    assert "const WEEKS = 7;" in render and "const WEEKS = 8;" not in render


def test_history_heatmap_last_column_is_the_current_week(client):
    # Regression guard: the grid must be anchored so its LAST column is the CURRENT week (Sun–Sat containing
    # today), or today's check-in never renders. The old math (`WEEKS * 7 - 1` start offset) ended the grid
    # on the PREVIOUS Saturday, so the whole current week was missing except on Saturdays.
    html = client.get("/").get_data(as_text=True)
    render = html[html.index("function renderHeat("):html.index("function renderHeat(") + 1600]
    assert "today.getUTCDate() - today.getUTCDay() - (WEEKS - 1) * 7" in render   # anchor last column to this week, in UTC
    assert "WEEKS * 7 - 1" not in render                                          # the old (buggy) start offset is gone


def test_streak_and_heatmap_group_days_in_utc_not_local(client):
    # Check-ins are stored + de-duplicated by UTC day, so the client must group by UTC day too — else a
    # non-UTC user's evening/early check-in lands on the wrong day (ghost "future" cell, broken streak,
    # nag-after-checkin). CI runs in UTC so a LOCAL-date regression is invisible here — hence this guard.
    html = client.get("/").get_data(as_text=True)
    for fn in ("function computeStreak(", "function renderHeat("):
        block = html[html.index(fn):html.index(fn) + 1200]
        assert "setUTCHours" in block and "getUTCDate" in block          # uses the UTC clock
        assert "setHours(" not in block and ".getDate()" not in block    # ...and not the LOCAL clock


def test_second_same_day_checkin_asks_to_confirm_the_replace(client):
    # #5 consequence made explicit: a second check-in today REPLACES today's reading (one row/day). The
    # submit handler confirms before overwriting, keyed on the UTC day (the server's dedup key).
    html = client.get("/").get_data(as_text=True)
    assert "function hasCheckedInToday()" in html
    hc = html[html.index("function hasCheckedInToday()"):html.index("function hasCheckedInToday()") + 400]
    assert "new Date().toISOString().slice(0, 10)" in hc                          # UTC day = the server replace key (#5)
    handler = html[html.index('onSubmit("checkin-form"'):html.index('onSubmit("checkin-form"') + 1400]
    assert "hasCheckedInToday() && !confirm(" in handler                          # confirm before replacing
    assert "REPLACE today's reading" in handler                                   # the consequence is spelled out


def test_illustrated_empty_states(client):
    # Friendly illustrated empty states (icon + title + guidance) instead of a bare grey line, across
    # History / Forum / DM / the filtered lists (Wolt's empty cards).
    html = client.get("/").get_data(as_text=True)
    assert "function emptyState(" in html and 'class="empty"' in html and "EMPTY_ICONS" in html
    for title in ("No check-ins yet", "Quiet in here", "No conversations yet", "You haven't posted yet"):
        assert title in html
    assert ".empty-ico" in html and ".empty-title" in html         # the empty-state CSS is present


def test_danger_zone_groups_destructive_actions(client):
    # Logout + Delete are grouped in one red "Danger zone" card (Wolt-style destructive-in-red), moved out
    # of the Account card; the IDs are unchanged so the existing wiring/handlers still bind.
    html = client.get("/").get_data(as_text=True)
    assert "Danger zone" in html and 'class="card danger-zone"' in html
    assert 'id="logout-btn" class="ghost danger block"' in html     # logout is now red, inside the danger zone
    assert 'id="delete-reveal"' in html                             # delete lives here too
    assert ".danger-zone" in html                                   # the red-tinted card CSS


def test_dm_recipient_search_and_pick_present_and_wired(client):
    # The "To" field is a search-and-pick autocomplete (not a bare exact-handle box): a combobox with a
    # listbox dropdown backed by GET /users/search, debounced, keyboard-navigable, results HTML-escaped.
    html = client.get("/").get_data(as_text=True)
    assert 'id="dm-suggest"' in html and 'role="listbox"' in html
    assert 'role="combobox"' in html and 'aria-controls="dm-suggest"' in html
    assert "/users/search?q=" in html                               # wired to the search endpoint
    assert "function runDmSearch(" in html and "function pickDmUser(" in html
    assert "dmSearchSeq" in html                                    # race-guard against stale keystroke responses
    assert "escapeHtml(u.username)" in html and "escapeHtml(u.display_name)" in html  # XSS-safe rendering


def test_navigation_state_resets_on_reentry_and_switch(client):
    # Audit fixes: (HIGH-2) re-entering the Forum tab closes any stale open post-detail (so the list shows and
    # the FAB reads Home, not a wrong Back); (MED) switching accounts drops the DM search dropdown so a prior
    # user's results don't linger. Both mirror how Messages already resets its view on entry/switch.
    # #342 added the second half of "lands on the list": entry also RE-SYNCS it. onForumEvent drops pushes
    # that arrive while the forum is off-screen, so without a refetch on entry the list keeps showing whatever
    # it held when the user left — stale with no recovery but the Refresh button.
    html = client.get("/").get_data(as_text=True)
    assert 'if (name === "forum") { closePost(); loadForum({ quiet: true }); }' in html   # entry: list + fresh
    assert "dmPeer = null; closeDmSuggest();" in html              # account-switch clears the search dropdown


def test_display_name_prefill_is_smart_not_sticky(client):
    # The email -> display-name prefill keeps syncing until the user customises the name (tracks the last auto
    # value; resets on form-reset), and the field is autocomplete=off so the browser can't falsely freeze it
    # (the old sticky `touched` flag made it work once then die — reproduced live).
    html = client.get("/").get_data(as_text=True)
    assert "function wireDisplayNamePrefill(" in html
    assert "let lastAuto" in html and "nameEl.value === lastAuto" in html    # smart tracking, not a sticky flag
    assert 'form.addEventListener("reset"' in html                          # every fresh attempt starts clean
    assert 'id="reg-username" name="username" autocomplete="off"' in html   # no browser-autofill false-trip
    assert "let touched = false" not in html                                # the old buggy flag is gone


def test_register_email_verification_reuses_the_otp_screen(client):
    # Registration verifies the email BEFORE creating the account: a verify_required response routes to the OTP
    # screen in "register" mode. The screen is SHARED — submit + resend branch by otpMode, the "trust this
    # browser" row is hidden, and the CTA reads "create account".
    html = client.get("/").get_data(as_text=True)
    assert 'status === "verify_required"' in html                          # the register handler branches on it
    assert 'showOtp(r.data.expires_in, "register")' in html
    assert '"/register/verify"' in html and '"/register/resend"' in html   # verify + resend branch by mode
    assert 'id="otp-remember-row"' in html and 'id="otp-submit"' in html   # toggled per mode
    assert "Verify & create account" in html                               # the register-mode CTA


def test_debug_tools_panel_present_and_gated(client):
    # A DEBUG-only dev-tools panel: a bottom-right floating button opening a compact panel with a
    # desktop/mobile viewport preview (an iframe -> real narrow-viewport render) + a live/mock email
    # indicator. Hidden unless ?debug=1 / ws-debug, suppressed inside the preview iframe, zero footprint live.
    html = client.get("/").get_data(as_text=True)
    assert 'id="debug-fab"' in html and 'id="debug-panel"' in html
    assert "function wireDebugTools(" in html
    assert "if (!DEBUG) return" in html                             # gated on the DEBUG flag
    assert 'params.has("preview")' in html                         # not nested inside the preview iframe
    assert 'id="debug-vp-mobile"' in html and 'id="debug-preview-frame"' in html   # the viewport preview
    assert 'location.pathname + "?preview=1"' in html              # iframe = a real narrow-viewport render
    assert 'id="debug-email-mode"' in html                         # the live/mock indicator


def test_debug_tools_omitted_inside_preview_iframe(client):
    # The mobile preview loads this shell as an iframe at ?preview=1. The dev-tools markup must be GONE
    # from that render (server-side strip), so the preview can never nest its own dev tools into a
    # preview-in-a-preview recursion (#138). The normal shell keeps the markup (gated client-side).
    preview = client.get("/?preview=1").get_data(as_text=True)
    assert 'id="debug-fab"' not in preview
    assert 'id="debug-panel"' not in preview
    assert 'id="debug-preview-frame"' not in preview
    normal = client.get("/").get_data(as_text=True)
    assert 'id="debug-fab"' in normal                              # still present on the real shell
    # Belt-and-suspenders client guard: dev tools never wire up in ANY frame, not just via ?preview.
    assert "window.top !== window.self" in normal
