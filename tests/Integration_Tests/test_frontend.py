"""Frontend shell test — GET / serves the single-page app with its API hooks. OWNER: Lior.

WHAT THIS FILE PROVES, EXACTLY: that the served shell CONTAINS the markup, handlers and endpoint
references the app needs. It never executes a line of the page's JavaScript, so it cannot prove that
any of that code does what it is named after. What it does catch, cheaply and without a browser, is a
template break: a renamed id, a dropped handler, an endpoint the SPA calls that no longer exists.

WHAT PROVES THE BEHAVIOUR: the browser suite in tests/E2E_Tests, which drives a real Chrome against a
running stack at two viewports.

The names here read "…markup_and_handlers_are_served" rather than "…is_wired", because "wired" claimed
more than a grep can deliver (#447). Two mutations made that concrete: gutting validateCheckin() to
`return true`, and reducing escapeHtml(s) to `return String(s)` — each left the ENTIRE pytest suite
green — re-measured with escaping gutted, not one failure — while the
tests named for those very properties kept passing. Both are now killed at the browser layer, by the
check-in gate scenario and the XSS scenario respectively.

So: if you want to know whether a behaviour is really covered, look for it in tests/E2E_Tests. This
file tells you the page still ships the parts.
"""
import re

import pytest


def test_index_serves_html(client):
    """The single-page app is actually served as HTML — the one check that has to pass before any other frontend guard means anything."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type


def test_user_text_insertions_route_through_escapehtml(client):
    """Every place the page writes user- or AI-supplied text into innerHTML calls escapeHtml on the way, and no template placeholder ships unrendered.

    This checks the CALL SITES, which is a real invariant: a new field rendered without escapeHtml is
    a new injection point, and this is what catches it. It does NOT check that escapeHtml works —
    gutting the function to `return String(s)` leaves every assertion here true, because the call
    sites are untouched. That half is proven by the browser scenario "security: injected markup from
    another user never executes" in tests/E2E_Tests/scenarios.mjs, which posts a real payload through
    the UI and asserts it renders as text.
    """
    html = client.get("/").get_data(as_text=True)

    # -- dashboard escapes ai provided fields
    # The AI container's `state` + each recommendation are attacker-influenced (a compromised/buggy
    # ai service could return HTML). They must be escaped before innerHTML, like the forum already is.
    assert "escapeHtml(d.readiness.state" in html
    assert "escapeHtml(x)" in html  # each recommendation in the recs.map
    assert "escapeHtml(d.calories" in html

    # -- history escapes entry fields
    # History rows carry AI-generated assessment text + a timestamp -> escape before innerHTML.
    assert "escapeHtml(it.assessment" in html
    # timestamp is now shown as a relative time, still escaped: escapeHtml(timeAgoStr(it.timestamp))
    assert "escapeHtml(timeAgoStr(it.timestamp))" in html
    assert "escapeHtml(it.calories" in html

    # -- forum list escapes post id
    # post id is interpolated into a data-id HTML attribute; a store-supplied id must be escaped too.
    assert "escapeHtml(p.id)" in html

    # -- served html has no unrendered template placeholders
    # guard against the raw `{{ ... }}` bug: the served shell must carry no template placeholders.
    assert "{{" not in html and "}}" not in html


def test_todays_checkin_markup_and_handlers_are_served(client):
    """Today / check-in: the form, its scales and live validation, the saved-flash, the streak badge and the due-capsule."""
    html = client.get("/").get_data(as_text=True)

    # -- daily checkin section present and wired
    # the check-in form posts today's readiness metrics to /checkin.
    assert 'id="checkin-form"' in html
    assert "/checkin" in html
    for field in ["sleep_hours", "resting_hr", "fatigue", "soreness", "training_load"]:
        assert f'name="{field}"' in html

    # -- checkin scales and live validation are wired
    # The 1–10/0–10 fields are colour-coded tap scales backed by a hidden input (same POST body); the two
    # typed fields validate live, and Submit stays greyed (aria-disabled) until every field is valid.
    for field in ["fatigue", "soreness", "training_load"]:
        assert f'data-field="{field}"' in html                     # the scale builds from this
        assert f'type="hidden" id="{field}"' in html               # hidden input carries the chosen value
    assert "function buildScales(" in html and "function validateCheckin(" in html
    assert "function updateCheckinValidity(" in html
    assert 'button type="submit" class="block" aria-disabled="true"' in html   # greyed until valid
    assert 'class="field-err" data-for="sleep_hours"' in html      # live per-field error
    assert 'class="field-err" data-for="resting_hr"' in html

    # -- checkin saved flash auto dismisses
    # #355: the "Check-in saved." success is a TRANSIENT toast — it auto-clears after a few seconds so it can't
    # linger on the Today screen or reappear when the user navigates back to it. Errors are NOT auto-cleared.
    assert "function checkinFlashOk(msg)" in html                              # the auto-dismiss helper
    assert 'setTimeout(() => flash("checkin-flash", "", "ok"), 4000)' in html  # ...clears the flash after a few seconds
    assert 'checkinFlashOk("Check-in saved.")' in html                         # the success path uses it
    assert 'flash("checkin-flash", "Check-in saved."' not in html              # the old lingering (never-cleared) flash is gone

    # -- checkin streak badge present and wired
    # A consecutive-day streak badge on Today (Wolt's tenure footer -> fitness motivation), computed on
    # the client from the loaded history and rendered whenever history loads (login + after a check-in).
    assert 'id="streak-badge"' in html
    assert "function computeStreak(" in html and "function renderStreak(" in html
    assert "renderStreak(items)" in html                 # driven from loadHistory -> updates after each check-in
    assert "-day streak" in html                         # the badge copy

    # -- checkin due capsule present and wired
    # Wolt's 'shown-only-when-relevant' capsule: a floating nudge that appears ONLY when today's check-in
    # is missing AND you're not already on Today (where the form lives). Tapping it jumps to the form.
    assert 'id="checkin-capsule"' in html
    assert "function updateCheckinCapsule(" in html
    assert 'checkinDue && currentScreen !== "today"' in html   # the two-part relevance gate
    assert "checkinDue = streak.hasHistory && !streak.loggedToday" in html   # driven from the streak/history
    assert 'showScreen("today")' in html and "scrollIntoView" in html        # tap -> Today + the check-in form


def test_history_markup_and_handlers_are_served(client):
    """History: the detail view, real stored scores, the sort toggle, the 7-week heatmap and the filter/sort chips."""
    html = client.get("/").get_data(as_text=True)

    # -- history detail view is wired
    # #354: tapping a History row or a heatmap cell opens a detail modal showing that check-in's inputs, readiness
    # + per-state confidence, calories, and recommendations. The modal is BODY-level (a fixed child of a hidden
    # .screen wouldn't paint); rows/cells are keyboard-accessible; recommendations degrade for pre-#354 entries.
    assert 'id="history-detail"' in html and 'id="hdetail-body"' in html          # the modal shell exists
    assert "function openHistoryDetail(entry)" in html                            # populated from the in-memory entry
    assert 'data-ts="' in html and 'aria-label="View this check-in' in html        # rows carry their entry + are labeled buttons
    assert 'data-day="' in html                                                   # heatmap cells (with a check-in) are tappable
    assert '"hd-recs"' in html                                                    # the recommendations list renders
    assert "for this check-in." in html                                          # graceful fallback copy for missing recs
    assert 'e.key === "Escape"' in html                                          # ESC closes the modal

    # -- open dialogs lock the page behind them (#422, reproduced live on prod)
    # A position:fixed overlay does NOT stop the page scrolling underneath: past the card's own scroll end
    # (or starting the gesture on the backdrop) the scroll chains through and the History list visibly moves
    # under the blur. Both full-screen dialogs (this modal + the media lightbox) share one ref-counted lock.
    assert "function lockPageScroll()" in html and "function unlockPageScroll()" in html
    assert 'document.documentElement.style.overflow = "hidden"' in html          # the lock actually locks...
    assert 'document.body.style.overflowY = "hidden"' in html                    # ...on BOTH elements — the body is the
                                                                                 # real scroll container (121px crept
                                                                                 # through an html-only lock, measured)
    # both dialogs go through the shared openModal/closeModal, which lock, trap Tab and restore focus (#430)
    assert 'openModal($("history-detail"), $("hdetail-close"));' in html         # locked + focused on a real open
    assert "if (el) closeModal(el);" in html                                     # ...and released on a real close
    assert 'openModal(lb, lb.querySelector(".lightbox-close"))' in html          # the lightbox locks too...
    assert "const close = () => { if (closeModal(lb)) lbImg.src = \"\"; };" in html  # ...and releases on close
    assert "overflow-y:auto; overscroll-behavior:contain;" in html               # THE CARD's inner scroll can't chain

    # -- #424: a fixed dialog nested in a hidden screen opens 0x0 — invisible, not hit-testable — and once
    # the #422 lock exists that FREEZES the page with no tappable way out (only ESC, which touch lacks).
    # The lightbox lived inside #dm-thread-view and forum attachments carry data-full, so tapping a forum
    # photo froze the page. Both full-screen dialogs must be BODY-level, and the opener must refuse to lock
    # for an overlay that did not paint.
    body_tail = html[html.index('<div id="menu-backdrop"'):]                     # the body-level dialog block
    assert '<div id="lightbox"' in body_tail, "the lightbox must be body-level, not nested in a screen"
    assert '<div id="history-detail"' in body_tail
    dm = html[html.index('id="dm-thread-view"'):html.index('<div id="menu-backdrop"')]
    assert 'id="lightbox"' not in dm, "the lightbox must not live inside the DM thread view again"
    assert "if (!lb.getBoundingClientRect().width) {" in html                    # did-not-paint -> back out
    assert 'lbImg.src = ""; closeModal(lb);' in html                             # ...releasing the lock
                                                                                 # (site-specific — other elements
                                                                                 # legitimately use contain elsewhere)

    # -- history detail regenerates recs for pre 354 entries
    # #354 backfill: opening a pre-#354 entry (no recommendations) recomputes them on demand from its inputs via
    # POST /history/recommendations, showing a "Generating…" line that's swapped for the list when it returns.
    assert "async function regenerateHistoryRecs(entry)" in html
    assert '"/history/recommendations"' in html                                   # the backfill endpoint
    assert 'id="hd-recs-pending"' in html                                         # the "Generating…" placeholder
    assert "if (canRegen) regenerateHistoryRecs(entry)" in html                   # fired only for regenerable old entries
    assert "hdetailTs !== ts" in html                                             # guarded to the still-open entry (no cross-entry paint)

    # -- history rows show the real readiness score not the band level
    # issue #1: History used to show the band LEVEL (readinessClass -> 100/66/33). It now shows the SAME
    # 0-100 score the dashboard computes, from each entry's stored proba (band-centre fallback for old
    # entries with no proba) — so the dashboard's 84 and History agree instead of showing 84 vs 100.
    render = html[html.index("function renderHistoryList()"):html.index("function updateHistoryDirLabel()")]
    assert "readinessScore({ state: it.assessment, proba: it.proba })" in render   # real score from stored proba
    assert 'class="hrow-score">\' + score' in render                               # ...is what the row prints
    assert "] = readinessClass(it.assessment)" in render                           # class still drives the colour
    assert "+ pct +" not in render                                                 # the old band-level number is gone

    # -- history has a sort direction toggle defaulting newest first
    # UX (2026-07-15): History gained a Forum-style asc/desc toggle, defaulting to newest-on-top. The sort
    # is display-only (a .slice() copy) so the trend/heatmap/streak keep their stored chronological order.
    assert 'id="history-dir"' in html                                           # the toggle exists in the filter row
    assert 'historyDir = "desc"' in html                                        # default = newest first
    render = html[html.index("function renderHistoryList()"):html.index("function updateHistoryDirLabel()")]
    assert "items.slice().sort(" in render and "historyDir" in render           # display list is sorted (on a copy)
    assert "localeCompare" in render and ".timestamp" in render                 # ...by timestamp
    # the toggle flips direction and re-renders; filter chips stay scoped to [data-filter]
    assert 'chip.id === "history-dir"' in html                                  # the toggle branch is wired
    assert 'querySelectorAll(".chip[data-filter]")' in html                     # dir button isn't toggled "active"

    # -- history heatmap is seven weeks
    # The readiness heatmap is a 7x7 square (7 weeks x 7 days), driven by the single WEEKS constant.
    render = html[html.index("function renderHeat("):html.index("function renderHeat(") + 1600]
    assert "const WEEKS = 7;" in render and "const WEEKS = 8;" not in render

    # -- history heatmap last column is the current week
    # Regression guard: the grid must be anchored so its LAST column is the CURRENT week (Sun–Sat containing
    # today), or today's check-in never renders. The old math (`WEEKS * 7 - 1` start offset) ended the grid
    # on the PREVIOUS Saturday, so the whole current week was missing except on Saturdays.
    render = html[html.index("function renderHeat("):html.index("function renderHeat(") + 1600]
    assert "today.getUTCDate() - today.getUTCDay() - (WEEKS - 1) * 7" in render   # anchor last column to this week, in UTC
    assert "WEEKS * 7 - 1" not in render                                          # the old (buggy) start offset is gone

    # -- filter sort chips present and wired
    # Wolt-style filter chips: History filters by readiness (All/Ready/Moderate/Rest); Forum sorts
    # (Recent/Top/Mine). Client-side over the cached list; the active chip is highlighted.
    assert 'id="history-filters"' in html and 'id="forum-sorts"' in html
    for f in ('data-filter="all"', 'data-filter="ready"', 'data-filter="moderate"', 'data-filter="rest"'):
        assert f in html
    for s in ('data-sort="recent"', 'data-sort="top"', 'data-sort="mine"'):
        assert s in html
    assert "function renderHistoryList(" in html and "function renderForumList(" in html
    assert "historyFilter" in html and "forumSort" in html         # the filter/sort state drives the render

    # -- filter sort chips keep newest on the row
    # #353: on a narrow screen the "↓ Newest" sort chip must stay on the filters' row, not wrap to a line of its
    # own. The filters/sorts wrap inside a .chip-group; the ".dir" sort chip is its SIBLING, pinned top-right.
    assert "#history-filters, #forum-sorts { flex-wrap:nowrap;" in html        # the row itself never wraps
    assert "#history-filters .chip-group, #forum-sorts .chip-group" in html    # the chips wrap inside their group
    assert '<div class="chip-group">' in html                                  # the group wraps the filter/sort chips
    assert 'id="history-dir" class="chip dir"' in html and 'id="forum-dir" class="chip dir"' in html  # sort chip stays a sibling


def test_app_shell_navigation_and_theme_markup_is_served(client):
    """Shell: nav pill / FAB / logo-home, screen regions and cross-fade, reset-on-reentry, theme + dark-mode a11y."""
    html = client.get("/").get_data(as_text=True)

    # -- profile lives in the corner menu not a bottom tab
    # Design decision: Profile/account is reached ONLY via the corner account menu (the Wolt pattern),
    # not via a redundant bottom-nav tab. The bottom tab bar is the 4 frequent sections; the corner
    # avatar owns identity + account. Guards against the two-Profiles redundancy creeping back.
    assert 'data-screen="profile"' not in html          # no bottom-nav Profile tab
    assert 'data-act="profile"' in html                 # the corner menu is the single Profile entry
    assert 'showScreen("profile")' in html              # ...and it still routes to the Profile screen
    for screen in ("history", "forum", "messages"):
        assert f'data-screen="{screen}"' in html        # the frequent section tabs remain
    assert 'data-screen="today"' not in html            # Today is the Home button now, not a tab

    # -- desktop home button present and wired
    # Desktop mirror of the mobile Home FAB: a Home button in the top nav (left of History) that appears only
    # off-Today and routes to Today. Wired DIRECTLY (not via data-screen), so Today stays out of the tab model
    # (the dual-nav invariant above still holds).
    assert 'id="nav-home"' in html and 'class="navlink nav-home"' in html
    assert 'data-screen' not in html.split('id="nav-home"')[1].split(">")[0]   # NOT a data-screen tab
    assert '$("nav-home").addEventListener("click", () => showScreen("today"))' in html
    assert "navHome.hidden = !offHome" in html                     # shown only off-Today, like the mobile FAB

    # -- home fab is always a home button
    # Wolt's 'home button only when not home': the FAB is shown off-Today, hidden on Today. It is ALWAYS a
    # Home icon (a back chevron there read as confusing) and ALWAYS goes to Today; the drill-in "back" lives
    # on the in-view close (the ✕ in a post / the ← Back in a DM thread), not on this button.
    assert 'id="ctx-back"' in html and "function updateCtxBack(" in html
    assert 'const offHome = currentScreen !== "today"' in html               # shown iff off-Today
    assert "CTX_HOME_ICON" in html and "CTX_BACK_ICON" not in html           # always a Home icon, never a back chevron
    assert '$("ctx-back").addEventListener("click", () => showScreen("today"))' in html   # always goes to Today
    assert "ctxBackTarget" not in html                             # the old drill-in target logic is gone

    # -- desktop logo is the home button
    # Desktop fix: the separate Home/Back button is HIDDEN on desktop (it shifted the whole header). Instead
    # the LOGO becomes the home button off-Today — a home icon appears inside the brand dot + clicking the
    # brand goes to Today in-app (no reload). The header is flagged .off-home to drive it. Mobile keeps ctx-back.
    assert 'class="brand-home-ico"' in html                        # the home icon lives inside the brand dot
    assert "header.off-home .brand-home-ico" in html               # shown on desktop when off-Today
    assert '.ctx-back { display:none; }' in html                   # ...and the separate button is gone on desktop
    assert 'const offHome = currentScreen !== "today"' in html     # off-Today drives both the FAB and the logo home-icon
    assert 'classList.toggle("off-home", offHome)' in html         # header flagged off-Today
    assert "if (currentUser) { e.preventDefault(); showScreen" in html         # the logo is an in-app home link

    # -- mobile nav pill is centered stable with an aligned fab
    # Wolt's mobile layout: a compact pill that stays CENTERED in a full-width rail and NEVER shifts, plus a
    # bottom-left Home FAB the SAME 56px height as the pill (both bottom:12) so they're vertically centered on
    # one line. The FAB appearing/disappearing must not move the pill.
    assert ".ctx-back { position:fixed; left:12px;" in html                    # bottom-left floating FAB
    assert "width:56px; height:56px" in html                                   # FAB is 56px == the pill height (aligned)
    assert "gap:4px; height:56px; padding:6px" in html                         # the pill's fixed 56px height
    assert "width: min(clamp(176px, 55vw, 216px), calc(100vw - 152px))" in html  # compact + capped so it never overlaps the FAB
    assert "justify-content:center" in html                                    # the pill is centered in its rail
    assert "has-ctx" not in html                                               # NO sideways shift — the pill is stable

    # -- today screen is a region not an orphaned tabpanel
    # a11y: Today is now reached via the Home button (mobile) / logo (desktop), NOT a tab. Its screen must be
    # a `region` (like Profile), not a `tabpanel` with no controlling tab — which violates the WAI-ARIA tabs
    # pattern (a tablist whose panel has no tab, and no selected tab on the Today view).
    assert 'id="screen-today" class="screen" role="region"' in html
    assert 'id="screen-today" class="screen" role="tabpanel"' not in html

    # -- screen switch has a subtle crossfade
    # #356: switching screens cross-fades instead of a hard snap. Primary path = the native View Transitions
    # API (a real old->new cross-fade); fallback (older Safari) = replaying a subtle entrance on the incoming
    # .screen. Either only toggles `hidden` (never re-mounts content — the old "jumpy flicker" came from tearing
    # content nodes down); reducedMotion() opts fully out.
    assert "document.startViewTransition" in html                          # native cross-fade is the primary path
    assert "::view-transition-old(root)" in html                           # its duration is tuned for a smoother feel
    assert "@keyframes screenSwap" in html                                 # the fallback keyframe exists
    assert '_screen.style.animation = "screenSwap' in html                 # ...applied to the incoming screen where VT is absent
    assert "void _screen.offsetWidth" in html                              # the reflow that actually restarts the fallback animation
    assert "if (!reducedMotion() && typeof document.startViewTransition" in html   # opt-out honored (no transition under reduced motion)

    # -- navigation state resets on reentry and switch
    # Audit fixes: (HIGH-2) re-entering the Forum tab closes any stale open post-detail (so the list shows and
    # the FAB reads Home, not a wrong Back); (MED) switching accounts drops the DM search dropdown so a prior
    # user's results don't linger. Both mirror how Messages already resets its view on entry/switch.
    # #342 added the second half of "lands on the list": entry also RE-SYNCS it. onForumEvent drops pushes
    # that arrive while the forum is off-screen, so without a refetch on entry the list keeps showing whatever
    # it held when the user left — stale with no recovery but the Refresh button.
    assert 'if (name === "forum") { closePost(); loadForum({ quiet: true }); }' in html   # entry: list + fresh
    assert "dmPeer = null; closeDmSuggest();" in html              # account-switch clears the search dropdown

    # -- theme toggle present and wired
    # accessibility: a VISIBLE System/Light/Dark control (the OS-only theme had no in-app switch), applied
    # before first paint (no flash) and persisted across visits.
    assert 'id="theme-group"' in html                          # the settings control exists in the Profile screen
    for v in ('value="system"', 'value="light"', 'value="dark"'):
        assert v in html
    assert 'data-theme="light"' in html                        # the CSS overrides the OS via the forced-theme attr
    assert 'localStorage.getItem("ws-theme")' in html          # persisted + applied pre-paint in the <head> script
    assert "theme-switching" in html                           # transitions suppressed during the swap -> no flicker

    # -- theme change has a single source of truth
    # the corner menu's theme segments and the Profile radios must both route through setTheme, so the two
    # controls can never drift out of sync (setTheme persists, applies, and mirrors every control).
    assert "function setTheme(" in html and "function syncThemeControls(" in html
    assert 'class="um-seg"' in html and 'data-theme="system"' in html and 'data-theme="dark"' in html
    assert "#user-menu-panel .um-seg" in html   # syncThemeControls mirrors the choice onto the menu segments

    # -- dark mode and a11y present
    # dark mode done right (declared scheme + light-mode adaptation) + keyboard/label a11y.
    assert "color-scheme" in html                       # native controls/scrollbars match the theme
    assert "prefers-color-scheme: light" in html        # respects an OS light preference
    assert ":focus-visible" in html                     # visible focus ring for keyboard users
    assert 'for="age"' in html and 'id="age"' in html   # labels associated with their inputs

    # -- account menu present and wired
    # Wolt-style corner account menu: an avatar button in the header opens a dropdown with the identity
    # block + quick actions (Profile / Theme / Log out). The menu is an accessible popup (aria-haspopup
    # + aria-expanded + aria-controls), and its logout routes through the shared doLogout.
    assert 'id="user-menu-btn"' in html and 'id="user-menu-panel"' in html
    assert 'aria-haspopup="menu"' in html and 'aria-controls="user-menu-panel"' in html
    assert 'data-act="profile"' in html and 'data-act="logout"' in html
    assert "function doLogout(" in html and "closeUserMenu()" in html   # one logout path, shared with the Profile button


def test_messaging_and_forum_markup_and_handlers_are_served(client):
    """Messaging + forum UI: the pinned DM pane, on-demand paging, recipient search, Enter-newline, owner edit/delete."""
    html = client.get("/").get_data(as_text=True)

    # -- open dm thread is a pinned single scroll chat pane
    # UX fix (2026-07-15): an open DM thread must be a fixed-height chat pane — the header (Back + peer) and
    # the composer stay PINNED and the message list is the ONLY scroll (no page-scroll AND inner-scroll, and
    # the Back button never scrolls away). Scoped to #dm-thread-view; toggled via a `thread-open` class.
    assert "#dm-thread-view > .card" in html and "flex-direction:column" in html      # the flex chat pane
    assert "#dm-thread-view .dm-thread { flex:1 1 auto; max-height:none; }" in html    # the message list is the single scroll
    assert "#screen-messages.thread-open .screen-head { display:none; }" in html       # redundant title hidden while in a thread
    assert 'classList.add("thread-open")' in html and 'classList.remove("thread-open")' in html   # toggled on open/close

    # -- dm pane is pinned between header and nav
    # #351/#352: the open DM pane is PINNED (position:fixed) between the sticky header and the floating nav,
    # anchored to their RUNTIME-MEASURED positions (sizeDmThreadPane) — never a hard-coded viewport guess.
    # Fixed => out of page flow, so page-scroll can't slide the Back button under the header (#351); its bottom
    # is anchored just above the nav, so the pane fills the space with no dead gap (#352). Live-verified on the
    # Docker stack at a mobile viewport: page overflow 0, forced scroll 0, Back never moves, gap-to-nav 12px.
    assert "position:fixed; left:50%; transform:translateX(-50%)" in html      # the pane is pinned to the viewport
    assert "top:var(--dm-pane-top" in html and "bottom:var(--dm-pane-bottom" in html   # anchored to measured header/nav
    assert "function sizeDmThreadPane()" in html                               # the runtime sizer exists
    assert 'setProperty("--dm-pane-top"' in html and 'setProperty("--dm-pane-bottom"' in html
    assert "sizeDmThreadPane();" in html                                       # called on thread open
    assert "addEventListener(e, sizeDmThreadPane)" in html                     # re-measured on resize / orientationchange

    # -- dm thread pages older history on demand
    # #331 (client half): the thread read is bounded server-side to the newest page (MESSAGE_PAGE_DEFAULT=50),
    # so the client must ACCUMULATE pages and let the reader fetch older history — otherwise a >50-message thread
    # is silently truncated with no way back. The thread keeps a deduped, oldest-first union (dmMsgs) and pages
    # strictly BEFORE its oldest message (created_at cursor), prepending without yanking the scroll position.
    assert "let dmMsgs = []" in html and "dmOldestCursor" in html and "dmMoreOlder" in html   # the accumulator + cursor + gate exist
    assert "function mergeDmMsgs(page)" in html                                                # newest/older pages fold in, deduped by id
    assert "byId.set(m.id, m)" in html                                                         # dedup keyed on the stable message id
    assert "async function loadEarlierDm()" in html and 'onclick="loadEarlierDm()"' in html    # the control is defined AND wired
    assert '"?before=" + encodeURIComponent(dmOldestCursor)' in html                           # it pages before the oldest held message
    assert "dmOldestCursor = dmMsgs[0].created_at" in html                                      # cursor advances to the new oldest (monotonic -> no loop)
    assert "if (older.length < DM_PAGE) dmMoreOlder = false" in html                            # a short page retires the control (start reached)
    assert "box.scrollTop = prevTop + (box.scrollHeight - prevHeight)" in html                  # prepend holds the reader's place
    assert "if (dmLoadingOlder || !dmMoreOlder || dmOldestCursor === null) return" in html      # re-entrancy / no-op guards

    # -- dm recipient search and pick present and wired
    # The "To" field is a search-and-pick autocomplete (not a bare exact-handle box): a combobox with a
    # listbox dropdown backed by GET /users/search, debounced, keyboard-navigable, results HTML-escaped.
    assert 'id="dm-suggest"' in html and 'role="listbox"' in html
    assert 'role="combobox"' in html and 'aria-controls="dm-suggest"' in html
    assert "/users/search?q=" in html                               # wired to the search endpoint
    assert "function runDmSearch(" in html and "function pickDmUser(" in html
    assert "dmSearchSeq" in html                                    # race-guard against stale keystroke responses
    assert "escapeHtml(u.username)" in html and "escapeHtml(u.display_name)" in html  # XSS-safe rendering

    # -- enter drops a line in chat forum and comments
    # UX (2026-07-15): Enter must insert a newline (line drop), not send/post, in the chat reply, forum post
    # body, and comments. The DM reply textarea sends only on Shift+Enter (plain Enter = newline); every
    # composer body is a <textarea> (a textarea never submits its form on Enter), including the comment field
    # which used to be a single-line <input> (Enter submitted it). Login + regular single-line forms keep the
    # default Enter=submit (they were never touched).
    assert 'e.shiftKey) { e.preventDefault(); $("dm-reply-form").requestSubmit()' in html                 # chat sends on Shift+Enter
    assert '&& !e.shiftKey) { e.preventDefault(); $("dm-reply-form")' not in html                         # the old send-on-plain-Enter is gone
    assert '<textarea name="body" placeholder="Add a comment"' in html                                    # comment is a textarea now
    assert '<input name="body"' not in html                                                               # no single-line body input remains (would submit on Enter)

    # -- forum owner edit delete wired
    # the detail view exposes edit/delete for the author's own posts, hitting PATCH/DELETE.
    assert "editPost()" in html and "deletePost()" in html
    assert 'method: "PATCH"' in html and 'method: "DELETE"' in html
    assert "p.mine" in html  # buttons only on own posts (server-computed per-viewer flag; preserves anonymity)


def test_account_and_auth_markup_and_handlers_are_served(client):
    """Account + auth UI: editing, deletion, privacy/export, the danger zone, register hints/prefill and email verification."""
    html = client.get("/").get_data(as_text=True)

    # -- account editing ui present and wired
    # the Account card exposes display-name + change-password editors, wired to the /account endpoints
    # (autocomplete tokens let a password manager fill current / suggest a new password).
    assert 'id="displayname-form"' in html and 'id="password-form"' in html
    assert "/account/display-name" in html and "/account/password" in html
    assert 'id="current-password"' in html and 'id="new-password"' in html
    assert 'autocomplete="current-password"' in html and 'autocomplete="new-password"' in html

    # -- delete account ui present and wired
    # GDPR erasure: a two-step delete gated by BOTH the password AND a typed "DELETE" confirmation
    # (the "Delete forever" button stays disabled until the word matches), then DELETEs /account.
    assert 'id="delete-reveal"' in html and 'id="delete-form"' in html
    assert 'method: "DELETE"' in html and '"/account"' in html
    assert 'id="delete-password"' in html and 'id="delete-confirm"' in html
    assert "syncDeleteBtn" in html                      # button-gating logic is wired
    assert '!== "DELETE"' in html                       # stays disabled until the exact word is typed

    # -- privacy and export ui present and wired
    # GDPR: an email-consent opt-in toggle + a "download my data" export button, wired to the endpoints.
    assert 'id="email-consent"' in html and 'id="export-btn"' in html
    assert "/account/email-consent" in html and "/account/export" in html
    assert "worksmarter-export.json" in html            # the export triggers a JSON file download

    # -- danger zone groups destructive actions
    # Logout + Delete are grouped in one red "Danger zone" card (Wolt-style destructive-in-red), moved out
    # of the Account card; the IDs are unchanged so the existing wiring/handlers still bind.
    assert "Danger zone" in html and 'class="card danger-zone"' in html
    assert 'id="logout-btn" class="ghost danger block"' in html     # logout is now red, inside the danger zone
    assert 'id="delete-reveal"' in html                             # delete lives here too
    assert ".danger-zone" in html                                   # the red-tinted card CSS

    # -- register hints are fetched from the config endpoint
    # the credential hints are JS-driven from /auth/config (single source of truth), not hardcoded.
    assert 'class="info"' in html
    assert "/auth/config" in html
    assert 'id="reg-username-tip"' in html and 'id="reg-password-tip"' in html

    # -- display name prefill is smart not sticky
    # The email -> display-name prefill keeps syncing until the user customises the name (tracks the last auto
    # value; resets on form-reset), and the field is autocomplete=off so the browser can't falsely freeze it
    # (the old sticky `touched` flag made it work once then die — reproduced live).
    assert "function wireDisplayNamePrefill(" in html
    assert "let lastAuto" in html and "nameEl.value === lastAuto" in html    # smart tracking, not a sticky flag
    assert 'form.addEventListener("reset"' in html                          # every fresh attempt starts clean
    assert 'id="reg-username" name="username" autocomplete="off"' in html   # no browser-autofill false-trip
    assert "let touched = false" not in html                                # the old buggy flag is gone

    # -- register email verification reuses the otp screen
    # Registration verifies the email BEFORE creating the account: a verify_required response routes to the OTP
    # screen in "register" mode. The screen is SHARED — submit + resend branch by otpMode, the "trust this
    # browser" row is hidden, and the CTA reads "create account".
    assert 'status === "verify_required"' in html                          # the register handler branches on it
    assert 'showOtp(r.data.expires_in, "register")' in html
    assert '"/register/verify"' in html and '"/register/resend"' in html   # verify + resend branch by mode
    assert 'id="otp-remember-row"' in html and 'id="otp-submit"' in html   # toggled per mode
    assert "Verify & create account" in html                               # the register-mode CTA


def test_platform_surfaces_and_polish_markup_is_served(client):
    """Platform surfaces: the API contract the SPA calls, PWA + auto-update, gated debug tooling, and the visual polish pass."""
    html = client.get("/").get_data(as_text=True)

    # -- index references every api endpoint
    for endpoint in ["/register", "/login", "/logout", "/me", "/profile", "/dashboard", "/history", "/forum/posts"]:
        assert endpoint in html

    # -- index wires the pwa
    # the shell links the manifest + theme-color + apple icon and registers the service worker.
    assert 'rel="manifest"' in html and 'name="theme-color"' in html
    assert 'rel="apple-touch-icon"' in html
    assert "serviceWorker" in html and "/sw.js" in html

    # -- index registers the auto update loop
    # The home-screen app refreshes itself: it listens for a new worker taking control and re-checks on
    # foreground. Pin both so the auto-update behavior can't be silently dropped.
    assert "controllerchange" in html, "the reload-on-new-worker hook was removed (no auto-update)"
    assert "reg.update()" in html, "the foreground update check was removed (backgrounded PWA won't refresh)"

    # -- debug tracing is gated off by default
    # a gated debug tracer (Week-9 "logging has a cost"): OFF for normal users, ON via ?debug=1 or
    # localStorage "ws-debug" — so the bug-prone async/session/SSE paths are traceable without spamming
    # a normal user's console. The #109 stale-paint site is instrumented.
    assert "function dbg(" in html and "if (DEBUG)" in html      # dbg no-ops unless the flag is set
    assert 'localStorage.getItem("ws-debug")' in html and 'has("debug")' in html
    assert 'dbg("stale paint bailed:' in html

    # -- debug tools panel present and gated
    # A DEBUG-only dev-tools panel: a bottom-right floating button opening a compact panel with a
    # desktop/mobile viewport preview (an iframe -> real narrow-viewport render) + a live/mock email
    # indicator. Hidden unless ?debug=1 / ws-debug, suppressed inside the preview iframe, zero footprint live.
    assert 'id="debug-fab"' in html and 'id="debug-panel"' in html
    assert "function wireDebugTools(" in html
    assert "if (!DEBUG) return" in html                             # gated on the DEBUG flag
    assert 'params.has("preview")' in html                         # not nested inside the preview iframe
    assert 'id="debug-vp-mobile"' in html and 'id="debug-preview-frame"' in html   # the viewport preview
    assert 'location.pathname + "?preview=1"' in html              # iframe = a real narrow-viewport render
    assert 'id="debug-email-mode"' in html                         # the live/mock indicator

    # -- ui polish present
    # UX guards: responsive collapse, double-submit guard, and aria-live flash regions.
    assert "@media (max-width:" in html            # profile grid collapses on mobile
    assert "btn.disabled = true" in html           # submit disabled while a request is in flight
    assert 'aria-live="polite"' in html            # flash messages announced to assistive tech

    # -- slack inspired polish present
    # Slack-style polish: an unread COUNT on the Chat nav (not just a dot), a recent-chats avatar strip,
    # and a frosted backdrop behind the open account menu.
    assert 'id="dm-avatar-strip"' in html and "function renderAvatarStrip(" in html   # recent-chats avatar row
    assert 'id="menu-backdrop"' in html and 'class="menu-backdrop"' in html            # menu frost element
    assert "bd.hidden = false" in html and "bd.hidden = true" in html                  # backdrop toggled with the menu
    assert 'text = n > 0 ? label : ""' in html                                         # the nav badge shows a count, not just a dot
    assert "if (d.textContent !== text) d.textContent = text" in html                  # ...written value-aware (#420: idle ticks mutate nothing)

    # -- illustrated empty states
    # Friendly illustrated empty states (icon + title + guidance) instead of a bare grey line, across
    # History / Forum / DM / the filtered lists (Wolt's empty cards).
    assert "function emptyState(" in html and 'class="empty"' in html and "EMPTY_ICONS" in html
    for title in ("No check-ins yet", "Quiet in here", "No conversations yet", "You haven't posted yet"):
        assert title in html
    assert ".empty-ico" in html and ".empty-title" in html         # the empty-state CSS is present

    # -- dashboard paints the last stored readiness instantly
    # perf (Lior's "the home score takes long to load"): the orb waits on the AI-backed /dashboard read, so
    # loadDashboard now paints today's STORED readiness from historyItems immediately (optimistic), then swaps in
    # the fresh AI result — and skips the swap when it's identical so an unchanged orb doesn't re-animate.
    assert "function paintReadiness(el, d, freshReveal)" in html                  # the render is reusable
    assert "function latestTodayEntry()" in html                                  # today's stored entry drives the instant paint
    assert "const opt = !(opts && opts.fresh) ? latestTodayEntry() : null" in html
    assert "const sameAsOptimistic" in html                                       # unchanged orb doesn't re-animate
    assert "loadHistory().then(() => loadDashboard())" in html                    # history loads first so the instant paint has data


def test_async_renderers_guard_against_stale_session_paint(client):
    """Every session-scoped renderer snapshots who is signed in before it waits, and abandons the paint if the session changed while it was waiting.

    Otherwise a slow response for one user overwrites the next user's screen after a fast sign-out and sign-in — one person's data rendered into another person's session.
    """
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


def test_touch_targets_meet_44px_minimum(client):
    """The compact secondary controls meet the recommended minimum tap size, so they stay usable with a thumb rather than demanding a precise tap.

    Guards against a later style edit silently shrinking them back.
    """
    css = client.get("/").get_data(as_text=True)
    assert css.count("min-height:44px") >= 3       # button.mini, .detail .close, .settings-group .seg
    assert css.count("min-width:44px") >= 2        # button.mini (icon buttons), .detail .close
    assert "padding-right:44px" in css             # a long post title stays clear of the absolute close ✕


def test_manifest_is_served_for_pwa(client):
    """The manifest is served with the right content type and carries a name, icons and a start URL — without all four the app cannot be installed to a home screen at all."""
    resp = client.get("/manifest.webmanifest")
    assert resp.status_code == 200
    assert "manifest" in resp.content_type              # application/manifest+json
    data = resp.get_json(force=True)
    assert data["name"] and data["icons"] and data["start_url"] == "/"


def test_service_worker_served_at_root_scope(client):
    """The worker is served from the root with the header that widens its scope, so it controls the whole app rather than only the directory it was served from."""
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    assert "javascript" in resp.content_type
    assert resp.headers.get("Service-Worker-Allowed") == "/"


def test_service_worker_is_stamped_with_a_build_version(client):
    """The build placeholder is replaced at serve time, so every deploy ships a worker with a new cache name and installed apps update themselves.

    If the raw placeholder leaked through, no release would ever reach an installed phone.
    """
    sw = client.get("/sw.js").get_data(as_text=True)
    assert "__BUILD__" not in sw, "the build placeholder was served unstamped (auto-update won't trigger)"
    assert re.search(r'CACHE\s*=\s*"ws-shell-[0-9a-f]{8}"', sw), "SW cache name must carry the build hash"


def test_service_worker_navigation_is_cache_first(client):
    """A page load is served from the cache before the network is tried, which is what lets the app open at all with no connection — and the ordering is asserted, not just the presence of both calls."""
    sw = client.get("/sw.js").get_data(as_text=True)
    assert "caches.match" in sw and 'req.mode === "navigate"' in sw
    nav_block = sw[sw.index('req.mode === "navigate"'):]
    nav_block = nav_block[:nav_block.index("return;")]
    assert "caches.match" in nav_block, "navigation must try the cache"
    assert nav_block.index("caches.match") < nav_block.index("fetch"), \
        "navigation must serve from cache before falling back to network"


def test_hero_display_font_is_actually_served(client):
    """The self-hosted font really is present and really is a valid font file.

    A guard on the wiring alone would pass while the bytes were missing from the image, and the first anyone would notice is the page rendering in a fallback font in front of an audience.
    """
    resp = client.get("/static/fonts/bricolage-800-latin-v1.woff2")
    assert resp.status_code == 200, "the self-hosted display font 404s — hero would fall back to system font"
    assert resp.get_data()[:4] == b"wOF2", "served bytes are not a valid woff2 font"


def test_responsive_dual_nav_present(client):
    """One codebase serves a genuine desktop layout and a genuine mobile layout, both driving the same navigation — so a phone asking for the desktop site lands on the desktop layout rather than a stretched mobile one."""
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


def test_mobile_nav_pill_is_translucent_and_ios_frosted(client):
    """The floating navigation is genuinely translucent — content shows through it — and carries the prefixed blur, without which the frosting silently disappears on iPhone and it renders as an opaque slab."""
    html = client.get("/").get_data(as_text=True)
    assert "background: linear-gradient(180deg, var(--glass-fill)" in html      # translucent glass fill (real alpha token)
    assert "--glass-fill: rgba(255,255,255,.12)" in html                        # the fill IS translucent (not an opaque slab)
    assert "var(--card) 90%, var(--bg)" not in html                            # NOT the old opaque background
    assert html.count("-webkit-backdrop-filter") >= 2                          # the pill AND the FAB frost on iOS
    assert "backdrop-filter: blur(26px) saturate(1.9) brightness(1.12)" in html  # upgraded liquid-glass frost


def test_dm_reopen_repaints_even_when_the_thread_is_unchanged(client):
    """Re-opening an UNCHANGED conversation must still repaint it.

    Opening a thread resets it to loading placeholders by writing the DOM directly, which leaves the render cache believing the old content is still there — so the identical HTML was skipped and the placeholders stayed up. The thread rendered the first time it was opened and was blank every time after.
    """
    html = client.get("/").get_data(as_text=True)
    start = html.index("async function openThread(")
    body = html[start:html.index("async function renderThread(", start)]   # the openThread function body
    assert "__lastHtml" in body and "undefined" in body, \
        "openThread must clear the setHtmlIfChanged __lastHtml cache when it resets #dm-thread to skeletons"


def test_checkin_capsule_hidden_over_an_open_dm_thread(client):
    """The floating check-in nudge hides while a conversation is open, where it used to sit on top of the message composer — and comes back on close.

    Re-showing it replays its entrance, so it cannot get stuck invisible on a backwards animation fill.
    """
    html = client.get("/").get_data(as_text=True)
    assert 'const threadOpen = $("dm-thread-view") && !$("dm-thread-view").hidden;' in html
    assert 'const show = checkinDue && currentScreen !== "today" && !threadOpen;' in html   # shows only when due, off-Today, no thread
    assert html.count("updateCheckinCapsule();") >= 3          # showScreen + openThread + closeThread (at least)
    # iOS fix: re-showing the capsule replays its entrance so it can't stay stuck on the `both` backwards fill (opacity:0)
    assert "if (show && wasHidden) {" in html
    assert "void el.offsetWidth;" in html


def test_mutations_and_uploads_surface_their_failures(client):
    """A failed action must never look like a success.

    Four paths used to swallow errors: delete and edit had no failure branch at all, so a refused request was a click that appeared to do nothing, and the attachment paths reported "Posted." even when every upload failed — the text landed and the photo vanished silently.
    """
    html = client.get("/").get_data(as_text=True)
    # deletePost: an in-flight guard (no false error on a double-click) + a failure flash.
    dp = html[html.index("async function deletePost("):html.index("function editPost(")]
    assert "deleteInFlight" in dp                                                   # guards the double-click 404
    assert 'flash("forum-flash"' in dp and "Couldn't delete" in dp                  # failure is surfaced
    # editPost save: a failure flash on a bad PATCH.
    ep = html[html.index("function editPost("):html.index("function cancelEdit(")]
    assert "Couldn't save your changes" in ep and 'flash("forum-flash"' in ep
    # forum-post upload: a dropped attachment downgrades the clean "Posted." to a warning...
    assert "couldn't be attached" in html                                          # the attachment-failure copy exists
    assert 'attachWarn ? "warn" : "ok"' in html                                    # forum + DM both branch the flash kind on the warn
    # ...and that warning has to be ACTIONABLE. The server distinguishes "unsupported media type" (400)
    # from "that file is too large" (413), but the upload discarded the body on `!res.ok`, so both — and a
    # dropped connection — produced one identical sentence. Two assertions only, both about the response
    # being READ: what the user is finally told is proven where it belongs, in the browser scenario
    # "messages: a refused attachment says which kind of file failed and why", which fails on the old
    # renderer with the exact wrong sentence. Restating that here in string-shape would pin the wording
    # rather than the behaviour, and break on a rewrite that is perfectly correct.
    um = html[html.index("async function uploadMedia("):html.index("async function uploadAll(")]
    assert "await res.json()" in um and "d.error" in um                            # the reason is read off the response...
    assert "if (!res.ok) return null;" not in um                                   # ...not thrown away before parsing
    # DM reply: a dropped attachment must not clear the flash to a silent success.
    dm = html[html.index('onSubmit("dm-reply-form"'):html.index('$("dm-files").addEventListener')]
    assert "attachWarn" in dm and 'flash("dm-reply-flash", attachWarn' in dm


@pytest.mark.parametrize(
    "surface, start, end, present, absent",
    [
        # Signing out is the one where being wrong is a security problem, not a UX one: a POST that never
        # landed leaves the session and the remember-cookie alive, so tearing the client down regardless
        # tells the user they are signed out while the next person to reload is inside the account. 401 is
        # excluded deliberately — it means the session is already gone, which is the outcome we wanted.
        # The absent needle is doing real work: preferring the server's `error` string drops "you are
        # still signed in", the only part of the sentence the reader has to act on. Driving the deployed
        # build with /logout forced to 503 showed exactly that — the message read "service unavailable".
        ("logout", "async function doLogout(", '$("logout-btn").addEventListener',
         ["if (!r.ok", "r.status !== 401", 'flash("logout-flash"', "you are still signed in"],
         ['flash("logout-flash", (r.data && r.data.error) ||']),
        # The dashboard paints a stored reading first so the orb is never blank. If the live read then
        # fails, dropping the error meant that stored reading was presented as today's result and Refresh
        # looked inert. The paint stays (it is real data); a notice says it is not fresh, and clears on the
        # next good read so a recovered panel does not keep an obsolete warning.
        ("dashboard", "async function loadDashboard(", "const sameAsOptimistic",
         ["staleNotice(", "clearStaleNotice("], []),
        # A deleted post and an unreachable server are different facts. "Please try again" is actionable
        # for one and false for the other, because a removed post never comes back.
        ("open a post", "function failOpen(", "async function openPost(",
         ["status === 404", "This post was removed."], []),
        # A search that failed is not a search that found nobody. Hiding the list is indistinguishable from
        # "no such person", so a blip reads as "that handle doesn't exist" and the sender gives up.
        # (the copy is inside a single-quoted JS string, so its apostrophe is served backslash-escaped —
        # match on the distinctive words instead of reproducing the escaping here)
        ("dm search", "async function runDmSearch(", '$("dm-to").addEventListener("input"',
         ["search just now", "dm-suggest-empty"], ["if (!r.ok) { closeDmSuggest(); return; }"]),
        # An unticked consent box is itself a claim — "you are opted out". After a failed read we do not
        # know that, and someone who opted IN would be shown the opposite of their own choice.
        ("email consent", "async function syncEmailConsent(", '$("email-consent").addEventListener',
         ["indeterminate = true", "disabled = true"], []),
    ],
)
def test_each_failure_surface_declares_a_branch_for_the_failure(client, surface, start, end, present, absent):
    """A request that fails has to leave the panel saying so — these five swallowed it in five different ways, each with its own wrong outcome: a live session shown as signed out, a stale reading shown as current, an impossible retry, a real person reported as nonexistent, and a consent state asserted without reading it.

    Read this for exactly what it is: proof that each failure BRANCH is present in the served page, not
    that it fires. The five are parametrized rather than merged because they fail independently — one
    regression should name its own surface instead of hiding behind the other four. What was actually
    driven end to end was the deployed build: each of the five was reproduced by forcing its response to
    fail in a real browser against the running app before the branch was written, and the wrong outcome
    listed above is what the app did.
    """
    html = client.get("/").get_data(as_text=True)
    block = html[html.index(start):html.index(end)]
    for needle in present:
        assert needle in block, f"{surface}: missing {needle!r}"
    for needle in absent:
        assert needle not in block, f"{surface}: still carries the swallowing path {needle!r}"


def test_the_new_post_body_is_capped_like_every_other_text_field(client):
    """The quick composer's body was the only text field in the app with no length cap, so a long paste sailed past the client and hit Flask's 64 KB request ceiling — which answers "that file is too large" for a post that has no file in it.

    5000 matches BODY_MAX in web/routes/forum.py and the edit form's own textarea, so the limit the user
    feels while typing is the limit the server actually enforces.
    """
    html = client.get("/").get_data(as_text=True)
    composer = re.search(r'<textarea name="body" placeholder="Share something[^>]*>', html)
    assert composer, "the quick-composer body textarea is no longer served"
    assert 'maxlength="5000"' in composer.group(0)


def test_forum_realtime_handler_is_served_with_its_guards(client):
    """The served shell carries the live-forum subscription and its handler, and that handler declares every guard the feature depends on: scoped to the forum screen, refreshing in place, never over a live draft, and closing a deleted open post with an accurate note.

    The negative assertions are the load-bearing ones — `openPost(currentPostId)` being ABSENT is what
    stops #420 coming back. But this is still a read of the served text: it shows the guards are
    declared, not that they fire. Unlike escaping and the check-in gate, this feature has no browser
    scenario behind it yet, so treat this as its only coverage and read it as such.
    """
    html = client.get("/").get_data(as_text=True)
    assert 'addEventListener("forum", onForumEvent)' in html            # subscribed to the forum push
    assert "function onForumEvent()" in html
    body = html[html.index("function onForumEvent()"):html.index("function startEvents()")]
    assert 'currentScreen !== "forum"' in body                                  # scoped to the forum screen
    assert "loadForum({ quiet: true })" in body                                 # ...refreshed IN PLACE (no skeleton flash)
    # #420: the open post is refreshed by the in-place patcher, NEVER by a full openPost teardown — the
    # SSE push and the 45s backstop route through here forever, and openPost recreates the attachment
    # <video> (resetting playback) plus the whole comments box on every single tick.
    assert "refreshOpenPost()" in body                                          # refreshes the open post in place
    assert "openPost(currentPostId)" not in body                                # the teardown path is gone
    assert "document.activeElement" in body and ".value.trim()" in body         # ...but not over a live draft
    # If the OPEN post was deleted live, close it with an accurate note — NOT re-fetch it (a 404 -> the
    # generic "couldn't open, try again", which is misleading when the post is simply gone).
    assert "forumPosts.some((p) => p.id === currentPostId)" in body             # detect the open post vanished
    assert "This post was removed." in body                                     # accurate copy for a live delete
    # loadForum must actually honour the quiet flag (skip the skeleton) — else the guard above is cosmetic.
    lf = html[html.index("async function loadForum("):html.index("function renderForumList()")]
    assert "opts && opts.quiet" in lf and 'sk("rows")' in lf                    # quiet -> no skeleton paint


def test_forum_realtime_has_a_self_healing_poll_backstop(client):
    """A stream can die in ways that leave it looking healthy, so a periodic poll restarts a closed stream AND re-syncs the feed.

    The re-sync must not be gated on the connection merely being open: a stream whose read failed once goes silent for its whole life while staying open, and a change landing in a reconnect gap is absorbed by the next stream's baseline and never sent. Connection state describes the CONNECTION, never the push path.
    It still skips while the reader has paged back or is typing, or the timer would harm the user it exists to help.
    """
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


def test_checkin_submit_frees_the_form_on_save_not_after_the_refresh(client):
    """Submit is disabled only while the check-in is being saved; the dashboard reload that follows runs in the background.

    Awaiting it meant a slow prediction left the button stuck grey with the user's values still on screen and no way to tell whether anything had been saved.
    """
    html = client.get("/").get_data(as_text=True)
    start = html.index('onSubmit("checkin-form"')
    handler = html[start:start + 3300]                                            # the check-in submit handler body
    assert '"Saving…"' in handler                                                 # in-flight feedback
    assert "await Promise.all([loadDashboard" not in handler                      # the refresh is NOT awaited
    assert "Promise.all([loadDashboard({ fresh: true }), loadHistory()]).then(countUpKcal)" in handler  # ...it's backgrounded
    assert 'f.reset(); resetCheckinScales(); updateCheckinValidity();' in handler  # form reset on save


def test_reset_link_survives_a_service_worker_reload(client):
    """A password-reset link must survive the automatic reload a new build triggers.

    The token is scrubbed from the URL immediately for safety, so without stashing it the reload dropped the user back to sign-in holding a link they could not use twice. It is consumed on restore, so it survives exactly one reload and cannot trap them.
    """
    html = client.get("/").get_data(as_text=True)
    init = html[html.index("async function init()"):html.index("async function init()") + 1400]
    assert 'sessionStorage.setItem("pending_reset_token"' in init                 # stashed before the URL is scrubbed
    assert 'sessionStorage.getItem("pending_reset_token")' in init                # recovered after a reload
    assert 'sessionStorage.removeItem("pending_reset_token")' in init             # ...and consumed (survives ONE reload, no trap)
    assert 'sessionStorage.removeItem("pending_reset_token")' in html[html.index('onSubmit("reset-form"'):html.index('onSubmit("reset-form"') + 500]  # cleared on success


def test_streak_and_heatmap_group_days_in_utc_not_local(client):
    """Check-ins are stored and de-duplicated by UTC day, so the client must group by UTC day too — otherwise a user in another timezone sees an evening check-in land on the wrong day, breaking their streak and nagging them for a check-in they already did.

    CI runs in UTC, so a regression to local dates would be invisible here without this guard.
    """
    html = client.get("/").get_data(as_text=True)
    for fn in ("function computeStreak(", "function renderHeat("):
        block = html[html.index(fn):html.index(fn) + 1200]
        assert "setUTCHours" in block and "getUTCDate" in block          # uses the UTC clock
        assert "setHours(" not in block and ".getDate()" not in block    # ...and not the LOCAL clock


def test_second_same_day_checkin_asks_to_confirm_the_replace(client):
    """A second check-in the same day replaces the first, so the user is asked before it happens — and the confirmation is keyed on the same day boundary the server uses, so what is warned about is what occurs."""
    html = client.get("/").get_data(as_text=True)
    assert "function hasCheckedInToday()" in html
    hc = html[html.index("function hasCheckedInToday()"):html.index("function hasCheckedInToday()") + 400]
    assert "new Date().toISOString().slice(0, 10)" in hc                          # UTC day = the server replace key (#5)
    handler = html[html.index('onSubmit("checkin-form"'):html.index('onSubmit("checkin-form"') + 1400]
    assert "hasCheckedInToday() && !confirm(" in handler                          # confirm before replacing
    assert "REPLACE today's reading" in handler                                   # the consequence is spelled out


def test_debug_tools_omitted_inside_preview_iframe(client):
    """The development tools are stripped from the embedded preview render, so the preview cannot nest its own preview inside itself indefinitely.

    The real page keeps them, gated on the client side.
    """
    preview = client.get("/?preview=1").get_data(as_text=True)
    assert 'id="debug-fab"' not in preview
    assert 'id="debug-panel"' not in preview
    assert 'id="debug-preview-frame"' not in preview
    normal = client.get("/").get_data(as_text=True)
    assert 'id="debug-fab"' in normal                              # still present on the real shell
    # Belt-and-suspenders client guard: dev tools never wire up in ANY frame, not just via ?preview.
    assert "window.top !== window.self" in normal


def test_forum_rows_render_like_and_dislike_tallies(client):
    """The served SPA must PRINT both tallies on the feed row, the post detail and every comment (#409).

    The API can carry `likes`/`dislikes` perfectly and still fail the sub-requirement if the template only
    prints the net score — which is exactly the state this replaced. Pinning the render sites here catches a
    revert to a score-only row in CI, where no browser is available to look at the page.
    """
    html = client.get("/").get_data(as_text=True)
    assert "function countPill(" in html                       # the shared tally renderer exists
    # the feed row carries both tallies as icon pills (it has no vote buttons of its own)...
    assert 'countPill(p.likes, "like")' in html and 'countPill(p.dislikes, "dislike")' in html
    # ...while the post detail and every comment print the number INSIDE its own vote button (`bare`), so a
    # count can never be read against the wrong button.
    assert 'countPill(p.likes, "like", true)' in html and 'countPill(p.dislikes, "dislike", true)' in html
    assert 'countPill(c.likes, "like", true)' in html and 'countPill(c.dislikes, "dislike", true)' in html
    # the net score is no longer printed as the only signal on the detail row
    assert '<span class="pill">score ' not in html
    # After a comment vote the client patches THAT row in place (it must not drop already-loaded older
    # pages), so the patch has to carry the tallies too — patching only the score would leave the row's
    # like/dislike numbers stale on screen until the whole thread was reloaded.
    vc = html[html.index("async function voteComment("):html.index("// ---- Media attachments")]
    assert "applyCommentTallies(commentId, r.data)" in vc     # patched IN PLACE (#428), never a full re-render
    assert 'typeof r.data.likes === "number"' in vc          # ...and falls back to a reload when they're absent


def test_forum_updates_patch_in_place_never_teardown(client):
    """#420: a vote / new comment / background tick must repaint NUMBERS, not rebuild the forum DOM.

    The old flow (openPost + a non-quiet loadForum on every vote, and openPost again on every SSE push and
    45s backstop tick) flashed the feed to skeleton rows, re-created the attachment <video> mid-play, and
    re-parented the open detail even when NOTHING had changed — the live app visibly "kept refreshing"
    forever. Pins the whole in-place contract so no future edit quietly reverts any leg of it.
    """
    html = client.get("/").get_data(as_text=True)

    # -- vote() patches in place off the #409 response; the teardown pair is gone
    v = html[html.index("async function vote(value)"):html.index("async function voteComment(")]
    assert "applyPostTallies(currentPostId, r.data)" in v
    assert 'typeof r.data.likes === "number"' in v                     # counts present -> zero refetches
    assert "openPost(currentPostId); loadForum();" not in v            # the old skeleton-flashing pair is gone
    assert "loadForum({ quiet: true })" in v                           # even the rare fallback resync is quiet

    # -- the patcher updates the data model AND both render sites, and keeps the row-cache honest
    ap = html[html.index("function applyPostTallies("):html.index("let voteInFlight")]
    assert "forumPosts.find(" in ap                                    # the cached list entry (sorts stay right)
    assert '.pill.count' in ap and ".tally" in ap                      # feed pills + detail tallies
    assert 'if (node && node.getAttribute("data-n") !== String(Number(v) || 0)) node.outerHTML = html;' in ap   # value-aware
    assert 'forumSort === "top" ? null : forumRowsKey()' in ap         # Top re-ranks; recent/mine skip the rebuild

    # -- renderForumList skips entirely when the rows it would paint are identical (the idle-tick fix)
    rl = html[html.index("function renderForumList()"):html.index("function togglePost(")]
    assert "if (el.__rowsKey === key) return;" in rl                   # no-change -> DOM untouched (exact line)
    assert "function forumRowsKey()" in html                           # ...keyed on the shared row builder
    assert "function forumRowHtml(" in html and "function visibleForumPosts(" in html
    # ...and a REAL rebuild restores what the re-parent broke: a playing attachment video AND a focused field
    assert "v.play().catch(() => {})" in rl                            # spec pauses a re-parented <video> — resume it
    assert "keepFocus.focus({ preventScroll: true })" in rl            # re-focus a blurred composer (caret kept)
    assert rl.count("restore();") >= 3                                 # ...on the empty-state early-returns too

    # -- the change-key must NOT self-invalidate on the wall clock: ages are keyed as a constant and rolled
    #    by a value-aware text write instead (else the whole list rebuilt once a minute for nothing)
    assert 'const age = forKey ? "×"' in html
    assert "function refreshRowAges()" in html
    assert "refreshRowAges();" in html[html.index("function onForumEvent()"):html.index("function pollBackstop()")]
    rra = html[html.index("function refreshRowAges()"):html.index("function forumRowsKey()")]
    assert "if (span.textContent !== text) span.textContent = text" in rra

    # -- sticky-null: a mid-Refresh skeleton marker must never be overwritten by open/close/tally writers,
    #    or the landing render skips and the skeletons strand forever (review HIGH)
    assert html.count("__rowsKey !== null") >= 3                       # openPost + closePost + applyPostTallies

    # -- the quiet loadForum path neither stashes the detail nor paints skeletons
    lf = html[html.index("async function loadForum("):html.index("async function loadMoreForum(")]
    assert 'if (!(opts && opts.quiet)) { stashDetail(); el.__rowsKey = null; el.innerHTML = sk("rows"); }' in lf
    # ...but its ERROR path must still stash before wiping: on a QUIET load nothing has stashed yet, and the
    # open detail lives INSIDE #forum-list — an unstashed wipe destroys it (the "can't open any post" wedge).
    assert "if (!r.ok) { stashDetail(); el.__rowsKey = null;" in lf

    # -- the background refresh of an OPEN post merges, guards, and never touches attachments
    rp = html[html.index("async function refreshOpenPost()"):html.index("async function voteComment(")]
    assert 'document.getElementById("edit-form")' in rp                # never repaints over an edit in progress
    assert "commentAccum.push(c)" in rp and "Object.assign(old, c)" in rp   # merge, never replace (#331 paging kept)
    assert "if (needsRender) renderComments()" in rp                   # re-render ONLY for a new/edited comment
    assert "applyCommentTallies(c.id, c)" in rp                        # a remote VOTE patches in place instead (#428)
    assert "/attachments" not in rp                                    # media never re-fetched by a background refresh
    assert rp.count('sessionChanged(u, "refreshOpenPost")') == 2       # cross-user stale-paint guard after BOTH awaits
    assert rp.count("seq !== refreshOpenSeq") == 2                     # overlapping refreshes: latest wins, after BOTH awaits
    assert "r.status === 404" in rp and '"This post was removed."' in rp    # a just-deleted post closes with the accurate note
    # a no-change tick writes NOTHING: the tally patcher bails before touching the DOM or the row-key
    ap = html[html.index("function applyPostTallies("):html.index("let voteInFlight")]
    assert "p0.score === d.score && p0.likes === d.likes && p0.dislikes === d.dislikes) return;" in ap

    # -- posting a comment refreshes in place too (no detail rebuild just to show one new row)
    assert "if (cr.ok) { f.reset(); refreshOpenPost(); }" in html
    assert "if (cr.ok) openPost(id);" not in html


def test_user_written_text_is_bidi_aware(client):
    """Hebrew content must lay out right-to-left (#426).

    The app is bilingual — users post in Hebrew and in English — but every user-written
    string was rendered inside the page's LTR paragraph direction. Measured on the real forum title
    "היום מציגים פרויקט בכתיבת תוכנה לML": the trailing Latin "ML" painted at x=263 (as if the line ended
    LTR) instead of x=32, and the Hebrew started at the left edge instead of the right. `dir="auto"` makes
    each string follow its OWN first strong character, so Hebrew goes RTL and English stays LTR — with no
    per-string language detection anywhere in the code.

    Only user-written text carries it. Chrome around it (the "by … · 3 comments · 3d ago" byline, the DM
    timestamp/tick) stays LTR, or a Hebrew name would drag the whole line's punctuation to the wrong side.
    """
    html = client.get("/").get_data(as_text=True)

    # forum: feed title, detail title, detail body
    assert '<strong dir="auto">\' + escapeHtml(p.title)' in html
    assert '<h3 dir="auto">\' + escapeHtml(p.title)' in html
    assert '<p class="body" dir="auto">\' + escapeHtml(p.body)' in html
    # comments: author name and body each follow their own direction
    assert '<strong dir="auto">\' + escapeHtml(c.author)' in html
    assert '<span dir="auto">\' + escapeHtml(c.body)' in html
    # DMs: the bubble follows the message, but its meta (time + delivery tick) stays LTR
    assert '<div class="\' + cls + \'" dir="auto">\' + escapeHtml(it.m.body)' in html
    assert '<span class="dm-meta" dir="ltr">' in html
    # inbox: peer name + last-message preview; activity feed line
    assert '<div class="dm-name" dir="auto">\' + escapeHtml(c.peer_name || c.peer)' in html
    assert '<div class="dm-last" dir="auto">\' + escapeHtml(c.last_message || "")' in html
    assert '<div class="dm-name" dir="auto">\' + escapeHtml(((n.actor' in html
    # bylines: ONLY the name is auto — the surrounding chrome must stay LTR
    assert '\'by \' + \'<span dir="auto">\' + escapeHtml(p.author) + \'</span>\'' in html
    assert 'by <span dir="auto">\' + escapeHtml(p.author) + \'</span></p>\'' in html
def test_updates_never_steal_focus_or_reading_position(client):
    """#428 — three sites still rebuilt a whole subtree for a small change.

    Each one is visible to a user who is simply reading or typing while a background tick or a teammate's
    action lands. #420 fixed this class for the forum LIST and the post detail; these are the three that
    were left.
    """
    html = client.get("/").get_data(as_text=True)

    # 1. a comment vote patches THAT row — the button the user pressed must survive (keyboard focus)
    assert "function applyCommentTallies(" in html
    ac = html[html.index("function applyCommentTallies("):html.index("async function voteComment(")]
    assert 'data-cid="\' + commentId + \'"' in ac                  # finds the live row
    assert 'if (node && node.getAttribute("data-n") !== String(Number(v) || 0)) node.outerHTML = html;' in ac   # value-aware, like #420
    assert "return false" in ac                                    # row off-screen -> caller re-renders
    # ...and the REMOTE path splits a vote from a real list change
    rp = html[html.index("async function refreshOpenPost()"):html.index("function applyCommentTallies(")]
    assert "tallyOnly.push(c)" in rp and "needsRender = true" in rp

    # 2. the activity feed keys its ages OUT of the change-string and rolls them with a text write,
    #    so a minute rollover cannot re-announce the aria-live region
    ra = html[html.index("function renderActivity("):html.index("function refreshActivityAges()")]
    assert '<div class="dm-last act-age"></div>' in ra             # age slot rendered EMPTY
    assert "escapeHtml(timeAgo(n.created_at))" not in ra           # ...never inside the keyed string
    assert "refreshActivityAges();" in ra                          # ...and renderActivity must call it
    assert "function refreshActivityAges()" in html
    aa = html[html.index("function refreshActivityAges()"):html.index("function refreshActivityAges()") + 700]
    assert "if (span.textContent !== text) span.textContent = text" in aa   # value-aware text write
    assert "span.textContent = text;\n" not in aa.replace("if (span.textContent !== text) span.textContent = text;\n", "")

    # 2b. the READ FLAG is kept out of that same change-string, for the same reason (#463). Marking the feed
    #     read alters no notification's content, so it must toggle a class on the live rows rather than
    #     re-render them. Measured before this: pressing "Mark all read" replaced all six rows (0 of 6
    #     survived by node identity), destroying the reader's selection and re-announcing the aria-live feed.
    assert '<div class="dm-row act" data-ts=' in ra                # the row class carries no read state...
    assert '(n.read ? "" : " unread")' not in ra                   # ...which is exactly what it used to do
    assert "refreshActivityRead(items);" in ra                     # ...renderActivity toggles it separately
    assert "function refreshActivityRead(items)" in html
    ar = html[html.index("function refreshActivityRead(items)"):html.index("function refreshActivityRead(items)") + 500]
    assert 'if (row.classList.contains("unread") !== unread) row.classList.toggle("unread", unread)' in ar

    # 3. a real forum rebuild puts the row the reader was looking at back under the same pixel
    rl = html[html.index("function renderForumList()"):html.index("function togglePost(")]
    assert "const anchorRow = [...el.querySelectorAll(\".post\")].find((d) => d.getBoundingClientRect().bottom > 0)" in rl
    assert "if (anchorId) {" in rl                                 # the anchor is actually consulted...
    assert 'el.querySelector(\'.post[data-id="\' + anchorId + \'"]\')' in rl   # ...to re-find the row
    assert "window.scrollBy(0, delta)" in rl


def test_dialogs_trap_and_restore_focus(client):
    """#430 — `aria-modal="true"` must actually hold, and focus must come back.

    Both full-screen dialogs DECLARED the rest of the page inert, but nothing enforced it: 89 focusable
    elements behind an open dialog stayed Tab-reachable (measured), so the ARIA promise was a lie to
    assistive tech. On close, focus was never returned to whatever opened the dialog — it landed on an
    unrelated button, losing a keyboard user's place in a 48-row list. The user menu already did this
    correctly (`closeUserMenu` → `btn.focus()`); these are the two that never got it.
    """
    html = client.get("/").get_data(as_text=True)

    # one shared implementation, so the two dialogs cannot drift apart
    assert "function openModal(dialog, focusTarget)" in html
    assert "function closeModal(dialog)" in html
    assert "function trapModalTab(dialog, e)" in html

    om = html[html.index("function openModal(dialog, focusTarget)"):html.index("function closeModal(dialog)")]
    assert "modalReturnFocus = document.activeElement" in om        # remember the trigger
    assert "lockPageScroll();" in om                                # ...and lock, in one place

    cm = html[html.index("function closeModal(dialog)"):html.index("function openHistoryDetail(entry)")]
    assert "if (dialog.hidden) return false;" in cm                 # idempotent -> the ref-count can't drift
    assert "unlockPageScroll();" in cm
    assert "modalReturnFocus.focus({ preventScroll: true })" in cm  # ...and hand focus back

    tm = html[html.index("function trapModalTab(dialog, e)"):html.index("function openModal(dialog, focusTarget)")]
    assert 'if (e.key !== "Tab" || dialog.hidden) return;' in tm
    assert "e.preventDefault(); last.focus();" in tm                # wraps backwards at the first element
    assert "e.preventDefault(); first.focus();" in tm               # ...and forwards at the last
    # pulls focus back if it ever escaped — BOTH directions, else a Shift+Tab from outside walks away
    assert tm.count("|| !dialog.contains(document.activeElement)") == 2

    # both dialogs are wired to it
    assert "document.addEventListener(\"keydown\", (e) => trapModalTab(modal, e));" in html   # history detail
    assert "trapModalTab(lb, e);" in html                                                     # lightbox

    # the account menu paints a full-screen backdrop, so it locks the page like the dialogs do
    ou = html[html.index("function openUserMenu()"):html.index("function openUserMenu()") + 700]
    assert "lockPageScroll();" in ou
    cu = html[html.index("function closeUserMenu()"):html.index("function openUserMenu()")]
    assert "if (wasOpen) unlockPageScroll();" in cu                 # released only on a REAL close


def test_read_loaders_have_supersede_guards(client):
    """#432 — an older in-flight response must never paint over a newer one.

    Every read-refresh loader already bailed on a session change, but only `loadForum` also had a SEQUENCE
    counter. Without one, two in-flight loads (a double-tapped Refresh, or a screen re-entry landing on top
    of a background poll) can resolve out of order and let the OLDER response paint last — showing stale
    readiness, history or inbox until the next event happens to correct it.
    """
    html = client.get("/").get_data(as_text=True)
    assert "let dashLoadSeq = 0, historyLoadSeq = 0, convLoadSeq = 0;" in html

    for fn, seq, end in (("loadDashboard(opts)", "dashLoadSeq", "async function loadHistory()"),
                         ("loadHistory()", "historyLoadSeq", "function renderHistoryList()"),
                         ("loadConversations()", "convLoadSeq", "function sizeDmThreadPane()")):
        body = html[html.index("async function " + fn):html.index(end)]
        assert f"seq = ++{seq}" in body, f"{fn} must claim a sequence number before its await"
        assert f"seq !== {seq}" in body, f"{fn} must drop a superseded response"
        # the guard has to sit on the SAME line as the session check, i.e. before any paint
        assert f'|| seq !== {seq}) return;' in body, f"{fn}'s supersede guard must gate the paint"


def test_profile_form_collects_f5_equipment_and_split_preference(client):
    """F5 (#276) plans from goal + training days + EQUIPMENT + SPLIT PREFERENCE. The first two were
    already collected; these two had no way into the app at all, so the generator could never be fed.
    Pins that the controls exist, that the submit actually sends them, and that a profile saved
    before they existed still loads without leaving stale boxes ticked."""
    html = client.get("/").get_data(as_text=True)

    # -- the controls are on the profile form
    assert 'id="split_preference" name="split_preference"' in html
    for split in ("no_preference", "full_body", "upper_lower", "push_pull_legs"):
        assert f'value="{split}"' in html, f"split option {split} missing from the form"
    for item in ("bodyweight", "dumbbell", "barbell", "kettlebell", "machine", "bands", "pullup_bar"):
        assert f'name="equipment" value="{item}"' in html, f"equipment option {item} missing from the form"

    # -- the submit sends them. `f.equipment` is a RadioNodeList across several checkboxes, so the
    #    handler must read the checked ones directly; f.equipment.value would send one wrong string.
    submit = html[html.index('onSubmit("profile-form"'):html.index('onSubmit("displayname-form"')]
    assert "split_preference: f.split_preference.value" in submit
    assert 'querySelectorAll(\'input[name="equipment"]:checked\')' in submit
    assert "f.equipment.value" not in submit

    # -- loading an OLD profile (neither key present) resets the controls instead of leaving
    #    whatever the previously-viewed profile had ticked.
    load = html[html.index("async function loadProfile"):html.index("async function loadEngagement")]
    assert 'p.split_preference || "no_preference"' in load
    assert "Array.isArray(p.equipment)" in load
    assert "c.checked = owned.includes(c.value)" in load


def test_equipment_pills_wrap_instead_of_giving_the_page_a_horizontal_scroll(client):
    """`.settings-group .seg-row` is a nowrap flex row built for the 3 theme pills. Seven equipment
    pills do not fit a phone width, so without an explicit wrap they overflowed the viewport and gave
    the whole PAGE a horizontal scroll (measured at 390px: pageScrollsX true -> false after the fix).
    Scoped to #equipment-group so the theme control keeps its single-row layout."""
    html = client.get("/").get_data(as_text=True)
    assert "#equipment-group .seg-row { flex-wrap:wrap; }" in html
    assert "#equipment-group .seg { flex:0 1 auto;" in html
    # the shared rule must stay nowrap — widening it would relayout the theme control too
    assert ".settings-group .seg-row { display:flex; gap:8px; margin-top:6px; }" in html


def test_boot_separates_unreachable_from_signed_out(client):
    """A boot `/me` that never completes is not the same as a server saying "not logged in", but the
    app treated both as "show the sign-in form" — so a user whose session was perfectly valid was
    asked for credentials that could not work, and concluded the app was broken (#440).

    `api()` already distinguishes them: a failed fetch returns the synthetic `status: 0`. This pins
    that boot branches on it, and that the offline state is a real sibling of the other auth
    sub-forms rather than a banner over a login form the user cannot use."""
    html = client.get("/").get_data(as_text=True)

    boot = html[html.index("async function bootSession()"):html.index("async function retryBoot(")]
    assert 'const r = await api("/me")' in boot
    assert "if (r.status === 0) showOffline(); else showTab(\"login\");" in boot, \
        "boot must send an unreachable server to the offline state, not to the login form"

    # -- the offline state exists, and is mutually exclusive with every other auth sub-form
    assert 'id="offline-form" hidden' in html
    assert 'id="offline-retry"' in html
    show_offline = html[html.index("function showOffline()"):html.index("let otpMode =")]
    for sibling in ("login-form", "register-form", "forgot-form", "reset-form", "otp-form"):
        assert sibling in show_offline, f"showOffline must hide {sibling}"
    # ...and every other sub-form must hide it back, or it would linger under them
    for fn, end in (("function showTab(", "function showForgot()"),
                    ("function showForgot()", "function showReset()"),
                    ("function showReset()", "// The auth card's"),
                    ("function showOtp(", "function showView(")):
        body = html[html.index(fn):html.index(end)]
        assert "offline-form" in body, f"{fn.strip('function (')} must hide the offline state"


def test_the_app_retries_by_itself_when_connectivity_returns(client):
    """Nothing in the SPA listened for `online`, so recovery meant the user retrying each panel by
    hand. Boot now re-runs on the browser's own signal — guarded, because `online` fires per
    interface change and un-guarded retries would stack overlapping /me calls."""
    html = client.get("/").get_data(as_text=True)
    assert 'window.addEventListener("online", () => retryBoot(false));' in html
    retry = html[html.index("async function retryBoot("):html.index('window.addEventListener("online"')]
    assert "bootRetrying = true;" in retry and "finally { bootRetrying = false; }" in retry


def test_auto_retry_cannot_disturb_a_user_mid_otp_or_mid_password_reset(client):
    """Regression. `online` fires on any interface change — a Wi-Fi flap, a VPN toggle — and the
    first version of this retry re-ran boot from wherever the user happened to be. On the OTP screen
    that meant /me returning 401 (nobody is signed in *yet*), which reset the auth card to the login
    tab: the code the user had just typed was discarded and its countdown stopped. The password-reset
    screen had the same exposure.

    `currentUser` does not guard it — it is assigned only in enterApp(), so it is null throughout
    both flows. The retry must additionally require that the offline state is the thing on screen,
    which is the only situation it exists for. Verified live: with the guard, the OTP form survives
    an `online` event with its code intact and its timer still counting down."""
    html = client.get("/").get_data(as_text=True)
    retry = html[html.index("async function retryBoot("):html.index('window.addEventListener("online"')]
    assert 'if (bootRetrying || currentUser || $("offline-form").hidden) return;' in retry, \
        "auto-retry must be inert unless the offline state is actually displayed"
    # the screens this protects must still be reachable sub-forms, or the guard is guarding nothing
    for fn in ("function showOtp(", "function showReset()"):
        assert fn in html


def test_forgot_password_does_not_promise_an_email_it_never_requested(client):
    """The handler flashed "a reset link is on its way" from a `||` fallback whenever the response
    carried no body — which is exactly what a dropped request (status 0) or a rate-limit 429 looks
    like. The user was sent to wait for an email nobody had asked for. The anti-enumeration wording
    on the SUCCESS path is deliberate and must survive untouched."""
    html = client.get("/").get_data(as_text=True)
    handler = html[html.index('onSubmit("forgot-form"'):html.index('onSubmit("reset-form"')]

    assert "if (!r.ok) {" in handler, "a refused or dropped request must not reach the success wording"
    # the failure branch has to come BEFORE the reassuring flash, or it changes nothing
    assert handler.index("if (!r.ok) {") < handler.index("reset link is on its way"), \
        "the failure branch must short-circuit before the success message"
    assert "r.status === 0" in handler, "a dropped request should read as a connection problem"
    assert 'reset link is on its way.", "ok")' in handler, "the hedged success wording must stay as-is"
