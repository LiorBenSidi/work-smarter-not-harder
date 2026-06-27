# PERSON 2 — Lior — the web app + its data

> Your area, the mandatory course items, and a roadmap. How you build the pages, structure the code, and model
> the data is your call. Your container: `web/` (the only one users reach).

## Start now — unblocked on day 1
`web` already calls the `ai /predict` **stub** (which returns the real contract) via `services/ai_client.py`, and
connects to the Mongo container. So you can build auth, profile, the dashboard, and `db.py` against the existing
stubs — in parallel, without waiting on the real model.

## Your contracts (fixed)
- Call the AI via `services/ai_client.py` → `POST /predict`.
- Connect to the Mongo container (`mongodb://db:27017`); the data code (`services/db.py`) is yours.
- `web` is the only exposed container (host 8000 → 5000).

## Mandatory (course — graded)
- **Password hashing with werkzeug** — never store plaintext.
- **Auth-gate** protected endpoints (logged-out → 401).
- **Validate input + NoSQL-injection-safe queries** before anything hits Mongo.
- **`debug` flag** — the app switches to debug mode when it's set.
- **Tests run on any machine** — security (wrong pw → 401, gated-without-login → 401, injection rejected) + integration (register → login → dashboard).

## Roadmap (build these — your way)
- [ ] **Auth (F1)** — `/register` `/login` `/logout`; hash; sessions/tokens; an auth-gate decorator.
- [ ] **Data layer** — `services/db.py`: connection + CRUD for `users / profiles / programs / analysis_history`; injection-safe.
- [ ] **Profile (F2)** — `/profile` route + page; save via `db`.
- [ ] **Dashboard (F7) + History (F8)** — current state (via `ai_client`), plan, calories, past analyses.
- [ ] **Frontend** — the `templates/` pages (or a JS frontend) + styling.
- [ ] **Forum:** the UI + post/comment/vote CRUD.

## You own the decisions
Page structure, server-rendered vs JS frontend, session vs token, the Mongo schema details inside `db.py` — your call.
