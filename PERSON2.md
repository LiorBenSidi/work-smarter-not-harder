# PERSON 2 — Lior — the web app + its data

> Your **area + the mandatory course items + a roadmap** — *not* a step-by-step script. How you build the pages,
> structure the code, and model the data is yours. Your container: `web/` (the ONLY container users reach).

## Why you
You're the strongest at building apps — so the whole user-facing service is yours, end-to-end: the pages, the auth,
the dashboard, **and** its data layer, so there's no hand-off in the middle of a feature.

## Your contracts (fixed)
- You **call the AI** through `services/ai_client.py` → `POST /predict` (don't talk to `ai` elsewhere).
- You **connect to the Mongo container Elad runs** (`mongodb://db:27017`) — but the data code (`services/db.py`) is **yours**.
- `web` is the only exposed container (host 8000 → 5000).

## Mandatory (course — graded)
- **Password hashing with werkzeug** — never store plain passwords.
- **Auth-gate** protected endpoints (profile, dashboard) — logged-out → 401.
- **Validate input + NoSQL-injection-safe queries** before anything hits Mongo.
- **Tests**: security (wrong pw → 401, gated-without-login → 401, injection rejected) + integration (register → login → dashboard).

## Roadmap (build these — your way)
- [ ] **Auth (F1)** — `/register` `/login` `/logout` (replace stubs); hash; sessions/tokens; an auth-gate decorator.
- [ ] **Data layer** — `services/db.py`: connection + CRUD for `users / profiles / programs / analysis_history`; injection-safe.
- [ ] **Profile (F2)** — `/profile` route + page; save via `db`.
- [ ] **Dashboard (F7) + History (F8)** — show current state (via `ai_client`), plan, calories, past analyses.
- [ ] **Frontend** — the `templates/` pages (or a JS frontend — your call) + styling.
- [ ] **Forum slice** — the UI/screens + post/comment/vote CRUD.

## You own the decisions
Page structure, server-rendered vs JS frontend, session vs token, the Mongo schema details inside `db.py` — your call. Keep the contracts + mandatory items.
