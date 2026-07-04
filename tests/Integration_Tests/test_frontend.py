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
    assert html.count('data-screen="today"') == 0                  # Today dropped -> Home reached via the FAB (mobile) / logo (desktop)
    assert "@media (min-width: 860px)" in html                     # the desktop breakpoint (the Request-Desktop switch)
    assert "max-width:920px" in html                               # wider desktop content
    assert 'document.querySelectorAll("[data-screen]")' in html    # showScreen + clicks drive both navs
    assert "function setDmDot(" in html                            # the Chat unread pulse toggles on both navs
    assert ".topnav.nav-on" in html                                # top-nav appears only when signed in


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
    # The mobile floating pill must be see-through (content shows behind it), not an opaque slab. That means
    # mixing the card colour with `transparent` (a real alpha), AND shipping the -webkit- prefix so the frosted
    # blur actually applies on iOS Safari (mobile is iOS Safari; without the prefix the blur silently no-ops).
    html = client.get("/").get_data(as_text=True)
    assert "color-mix(in srgb, var(--card) 64%, transparent)" in html          # translucent pill background
    assert "var(--card) 90%, var(--bg)" not in html                            # NOT the old opaque background
    assert html.count("-webkit-backdrop-filter") >= 2                          # the pill AND the FAB frost on iOS
    assert "backdrop-filter: blur(22px) saturate(1.5)" in html                 # blur kept for legibility


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
    html = client.get("/").get_data(as_text=True)
    assert 'if (name === "forum") closePost();' in html            # Forum tab-entry lands on the list
    assert "dmPeer = null; closeDmSuggest();" in html              # account-switch clears the search dropdown
