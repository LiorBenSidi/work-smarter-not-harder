# Mobile smoke test — run on a real iPhone before a release

Automated guards (`tests/Unit_Tests/test_frontend_mobile_guards.py`) fail CI if the code behind a
mobile fix is removed — but **no headless tool reproduces iOS Safari** (rubber-band overscroll, the
PWA home-screen name, `100dvh`, `position:fixed` quirks). So a **2-minute human check on an iPhone**
is the release gate for those. Do it against the live URL after a deploy that touched `web/`.

## The checklist (app.worksmarternotharder.dev, on an iPhone)
- [ ] **Overscroll** — swipe past the top and bottom of any screen → shows the **app colour** (dark/light), never white.
- [ ] **Nav bar** — switch History ⇄ Forum ⇄ Chat (short *and* long pages) → the bottom pill **stays pinned**, no wobble.
- [ ] **Password 👁** — on login / register / reset / settings, the eye toggles the password visible⇄hidden.
- [ ] **Forum** — tap a post → it **expands in place** with the chevron flipping; tap again → collapses.
- [ ] **Theme toggle** — Menu → Display & accessibility → System / Light / Dark are **three clean pills, no overlap**.
- [ ] **PWA name** *(only when the manifest changed)* — remove the old home-screen icon, **Add to Home Screen**, confirm the default name is **short** ("Work Smarter"). iOS reads the **manifest `name`** for this, and the manifest is cached — a rename needs a `?v=` bump on the link + SW `CACHE` (see `web/static/sw.js`), and the user may need to reopen the app once so the service worker updates.

### Design pass ⑦⑧⑨ (2026-07-11 — structure is auto-covered by E2E; these confirm it *feels* right on device)
- [ ] **Forum avatars** — each post row, the open post's author line, and every comment show a small coloured avatar disc; the **same person is the same colour** everywhere (matches their DM avatar). *(E2E asserts they render; this confirms the colours read cleanly at phone size.)*
- [ ] **Profile grouping** — the profile screen is **4 cards** (You · Preferences · Account · Danger), each with `.sep` hairlines between its sub-sections — not six separate floating cards. Scrolls cleanly, nothing cramped.
- [ ] **Hero score** *(needs a check-in with a readiness result)* — the big readiness number **counts up 0→N** in step with the ring filling; under iOS **Reduce Motion** it **snaps** to the final number (no count-up).
- [ ] **Focus ring** *(optional, needs an external/Bluetooth keyboard)* — Tab through the app → each control (buttons, a forum post row, theme pills) shows a **mint outline** on keyboard focus; tapping with a finger shows **no** ring.

## Why deploys reintroduce mobile bugs (and how we stop it)
1. **Silent code removal** → caught by the CI guard tests (they assert each fix's code is still present).
2. **Stale service-worker / manifest cache** → the app HTML is served `no-cache` (always fresh), but the
   **manifest + shell are SW-cached**; bump `CACHE` in `sw.js` (and version the manifest URL) whenever you
   change the manifest or want to force a shell refresh.
3. **iOS-only rendering** → this human checklist. Keep it to 2 minutes; run it before the demo/submission.
