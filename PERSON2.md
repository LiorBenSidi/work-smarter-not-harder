# PERSON 2 — Lior — the web application (backend + frontend)

> Your area, the mandatory course items, and a roadmap. How you build it is your call. Your container: `web/` —
> the application **backend** (Flask API, auth, request handling, orchestration) plus the frontend. The only container users reach.

## Your area — this is backend work (and backend is what's graded)
The course grades the **backend**, and `web` is the application backend:
- **API / routes** — `/register` `/login` `/logout` `/profile` `/dashboard` `/history` (the Flask endpoints + their logic).
- **Auth + sessions** — werkzeug hashing, login/session/token handling, the auth-gate decorator.
- **Request handling + validation** — parse and validate input (reject bad types) before it reaches `db`.
- **Orchestration** — call the AI (`ai_client` → `/predict`) and the DB (`db.py`), combine the results, and degrade gracefully when either is down (don't crash).
- **Thin core data-layer CRUD** (`services/db.py`) — the users/profiles/history/forum functions `web` calls. (The Mongo **container** + schema/indexes are Elad's.)
- **Frontend** — the templates/UI on top; not graded, but it matters for the demo vote.

## Start now — unblocked on day 1
`web` already calls the `ai /predict` stub (which returns the real contract) via `services/ai_client.py`, and reads/writes
data through the `services/db.py` thin-CRUD functions (yours). So you can build the backend (auth, the API routes, the
dashboard) against the in-memory fakes — in parallel, without waiting on the live Mongo container.

## Your contracts (fixed)
- Call the AI via `services/ai_client.py` → `POST /predict`.
- Read/write data via the `services/db.py` thin-CRUD functions (yours); the **Mongo container** + schema/indexes are Elad's.
- `web` is the only exposed container (host 8000 → 5000).

## Mandatory (course — graded)
- **Password hashing with werkzeug** — never store plaintext.
- **Auth-gate** protected endpoints (logged-out → 401).
- **Validate input** (reject bad types) before calling `db`.
- **Fault tolerance** — AI/DB down → the backend degrades, never crashes.
- **`debug` flag** — `FLASK_DEBUG` is already read in `config.py`; make the app actually honour it (debug mode on when set).
- **Tests run on any machine** — security (wrong pw → 401, gated-without-login → 401, injection rejected) + integration (register → login → dashboard).

## Roadmap — web tier COMPLETE (updated 2026-06-28)
- [x] **Auth (F1)** — `/register` `/login` `/logout` `/me`; werkzeug hashing; session gate (`login_required`); constant-time login (no user-enumeration); injection-safe validation; public `/auth/config` (credential bounds for the UI).
- [x] **Profile (F2)** — `/profile` GET/POST + validation (ranges, bool/type gate).
- [x] **Daily check-in (F3)** — `/checkin`: validate the daily metrics → `ai_client` `/predict` → save the entry to history; fault-tolerant (AI down → saved with no assessment; store down → 503).
- [x] **Dashboard (F7) + History (F8)** — readiness via `ai_client` (degrades when AI down), calories, `/history`.
- [x] **Frontend** — single-page UI + CSRF (double-submit) + responsive theming + a11y (focus, labels, aria-live) + credential tooltips driven by `/auth/config`; **a distinctive "performance-lab" visual identity** (readiness-verdict signature, teal/coral palette, monospace data).
- [x] **Forum** — UI + post/comment/up-down-vote CRUD (anonymity, XSS-escaped) + **edit/delete your own post (author-only)**.
- [x] **Thin core data-layer CRUD** (`services/db.py`) — users/profiles/history/forum fns + thread-safe `get_db` + `ensure_indexes` (unique constraints) + votes stored as a list (no username-keyed Mongo fields). **Concurrency-hardened** (atomic create-user dedupe, optimistic-concurrency vote, TOCTOU-safe edit/delete) + malformed-doc guards. In-memory fake for unit tests; a real-Mongo integration suite runs when a DB is up.
- [x] **Week-9 logging** — `logging_config.py` (console + rotating file, `ENABLE_LOGGING`/`LOG_LEVEL`, per-request access log with timing) wired at the gunicorn entrypoint (`wsgi.py`).
- [x] **Container build/run** — `web` (+ `ai`) Dockerfile + the runnable 3-container compose; fault-tolerance hardening on the shared compose (restart policies, healthcheck `start_period`, `web` boots and degrades even if `ai` is down). *(The Mongo container internals + Azure deploy/CD remain Elad's.)*

All gated/validated, adversarial + **mutation-tested**, independently QA-verified, live-browser-tested (dark/light/mobile). The web tier is feature-complete; remaining cross-team work is integration against Shiri's real model + Elad's deploy/Mongo/real-time.

## You own the decisions
Page structure, server-rendered vs JS frontend, session vs token, the API shape — your call. Keep the contracts + mandatory items.
