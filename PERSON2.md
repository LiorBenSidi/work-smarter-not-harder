# PERSON 2 — Lior — the web application (backend + frontend)

> Your area, the mandatory course items, and a roadmap. How you build it is your call. Your container: `web/` —
> the application **backend** (Flask API, auth, request handling, orchestration) plus the frontend. The only container users reach.

## Your area — this is backend work (and backend is what's graded)
The course grades the **backend**, and `web` is the application backend:
- **API / routes** — `/register` `/login` `/logout` `/profile` `/dashboard` `/history` (the Flask endpoints + their logic).
- **Auth + sessions** — werkzeug hashing, login/session/token handling, the auth-gate decorator.
- **Request handling + validation** — parse and validate input (reject bad types) before it reaches `db`.
- **Orchestration** — call the AI (`ai_client` → `/predict`) and the DB (`db.py`), combine the results, and degrade gracefully when either is down (don't crash).
- **Frontend** — the templates/UI on top; not graded, but it matters for the demo vote.

## Start now — unblocked on day 1
`web` already calls the `ai /predict` stub (which returns the real contract) via `services/ai_client.py`, and reads/writes
data through Elad's `services/db.py` functions. So you can build the backend (auth, the API routes, the dashboard) against
those stubs — in parallel, without waiting on the real model or DB code.

## Your contracts (fixed)
- Call the AI via `services/ai_client.py` → `POST /predict`.
- Read/write data via Elad's `services/db.py` functions (e.g. `create_user`, `get_profile`) — don't write Mongo queries yourself.
- `web` is the only exposed container (host 8000 → 5000).

## Mandatory (course — graded)
- **Password hashing with werkzeug** — never store plaintext.
- **Auth-gate** protected endpoints (logged-out → 401).
- **Validate input** (reject bad types) before calling `db`.
- **Fault tolerance** — AI/DB down → the backend degrades, never crashes.
- **`debug` flag** — `FLASK_DEBUG` is already read in `config.py`; make the app actually honour it (debug mode on when set).
- **Tests run on any machine** — security (wrong pw → 401, gated-without-login → 401, injection rejected) + integration (register → login → dashboard).

## Roadmap (build these — your way)
- [ ] **Auth (F1)** — `/register` `/login` `/logout`; hash; sessions/tokens; an auth-gate decorator.
- [ ] **Profile (F2)** — `/profile` route + page; save via `db`.
- [ ] **Dashboard (F7) + History (F8)** — current state (via `ai_client`), plan, calories, past analyses (via `db`).
- [ ] **Frontend** — the `templates/` pages (or a JS frontend) + styling.
- [ ] **Forum:** the UI + post/comment/vote CRUD.

## You own the decisions
Page structure, server-rendered vs JS frontend, session vs token, the API shape — your call. Keep the contracts + mandatory items.
