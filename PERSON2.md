# PERSON 2 — Lior — the web app

> Your area, the mandatory course items, and a roadmap. How you build the pages and structure the code is your
> call. Your container: `web/` (the only one users reach).

## Start now — unblocked on day 1
`web` already calls the `ai /predict` **stub** (which returns the real contract) via `services/ai_client.py`, and
reads/writes data through Elad's `services/db.py` functions. So you can build auth, profile, and the dashboard
against those stubs — in parallel, without waiting on the real model or the real DB code.

## Your contracts (fixed)
- Call the AI via `services/ai_client.py` → `POST /predict`.
- Read/write data via **Elad's `services/db.py` functions** (e.g. `create_user`, `get_profile`, `save_analysis`) — don't write Mongo queries yourself; that function API is the data seam.
- `web` is the only exposed container (host 8000 → 5000).

## Mandatory (course — graded)
- **Password hashing with werkzeug** — never store plaintext.
- **Auth-gate** protected endpoints (logged-out → 401).
- **Validate input** (reject bad types) before calling `db`.
- **`debug` flag** — the app switches to debug mode when it's set.
- **Tests run on any machine** — security (wrong pw → 401, gated-without-login → 401, injection rejected at the route) + integration (register → login → dashboard).

## Roadmap (build these — your way)
- [ ] **Auth (F1)** — `/register` `/login` `/logout`; hash; sessions/tokens; an auth-gate decorator.
- [ ] **Profile (F2)** — `/profile` route + page; save via `db`.
- [ ] **Dashboard (F7) + History (F8)** — current state (via `ai_client`), plan, calories, past analyses (via `db`).
- [ ] **Frontend** — the `templates/` pages (or a JS frontend) + styling.
- [ ] **Forum:** the UI + post/comment/vote CRUD.

## You own the decisions
Page structure, server-rendered vs JS frontend, session vs token — your call. Keep the contracts + mandatory items.
