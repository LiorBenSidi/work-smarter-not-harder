# PERSON 2 — Shiri — the web app (the user-facing service)

> Your **area + mandatory course items + a roadmap**. *Not* a step-by-step script — how you build the pages
> and structure the code is yours. Your container: `web/` (the ONLY container users reach).

## Your area, plainly
You own everything the **user sees and touches**: signing up, logging in, entering their profile, and the
dashboard that shows their readiness, plan, calories, and history. Your code is in `web/` (`app.py`, `routes/`,
`services/`, `templates/`). The route stubs already exist (returning **501**) — you replace each one with the real thing.

## Your contracts (fixed)
- You **call the AI** through `services/ai_client.py` → the ai container's `POST /predict` (don't talk to it directly elsewhere).
- You **read/write data** through `services/db.py` (Elad owns the DB internals; you call his functions).
- `web` is the only exposed container (host 8000 → 5000).

## Mandatory (course — graded)
- **Password hashing with werkzeug** (`generate_password_hash` / `check_password_hash`) — never store plain passwords.
- **Auth-gate** protected endpoints (profile, dashboard) — a logged-out user gets 401.
- **Validate input** (reject bad types; NoSQL-injection-safe) before anything reaches the DB.
- **Tests**: security (wrong password → 401, gated-without-login → 401, injection rejected) + integration (register → login → dashboard).

## Roadmap (build these — your way)
- [ ] **Auth (F1)** — implement `/register` `/login` `/logout` (replace the stubs); hash passwords; sessions/tokens.
- [ ] **Profile (F2)** — the `/profile` route/page (age/gender/height/weight/goal); save via `services/db`.
- [ ] **Dashboard (F7) + History (F8)** — show the user's current state (call the AI via `ai_client`), plan, calories, past analyses.
- [ ] **Frontend** — the pages in `templates/` (or a JS frontend — your choice) and the styling.

## You own the decisions
Page structure, server-rendered templates vs. a JS frontend, session vs. token auth, how you lay out `web/` — your
call. Just keep the contracts above and the mandatory items.
