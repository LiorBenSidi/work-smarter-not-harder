# PERSON 3 — Elad — infra, deploy, data & the real-time backend

> Your area, the mandatory course items, and a roadmap. How you build it is your call. You own the plumbing that
> runs and ships the app, the **data layer** (`services/db.py` + the Mongo container), plus the Forum's real-time
> backend. `docker-compose.yml` is your starting point.

## Start now — unblocked on day 1
The 3-container skeleton already runs, so you can start the Azure setup, the second compose file, the stress
harness, and the cross-container test harness immediately — none of it waits on the features.

## Your contracts (fixed)
- You own the **DB end-to-end**: the **Mongo container** (`db` service) **and** `web/services/db.py` (the data-access layer). `web` calls your `db.py` functions — that function API is the seam, so **stub the signatures early** so web isn't blocked.
- Only `web` is exposed (host 8000 → 5000); `ai` + `db` internal.

## Mandatory (course — graded)
- **docker-compose** (the base 3-container file already exists — extend it) — healthchecks, only `web` published (host 8000, never 5000).
- **`docker-compose.test.yml`** — a second compose for the test run (`TESTING=1`).
- **Never commit `.env`** (commit `.env.example`).
- **Rate limiting** (flask-limiter) on the public endpoints; defend against spammers.
- **Stress tests** (locust) — decide in advance what can crash, and defend it.
- **The deploy +10** — Azure deploy + CI auto-deploy on green (the CI gate already runs).

## Roadmap (build these — your way)
- [ ] **Data layer (`web/services/db.py`)** — CRUD for `users / profiles / programs / analysis_history` (a `get_db()` connection helper already exists); injection-safe queries; schema/indexes. Stub the function signatures early (web calls them).
- [ ] **Azure deploy + CI/CD** — extend the live pipeline to deploy on green `main`; scale via `ai` replicas + gunicorn workers. Start early.
- [ ] **`docker-compose.test.yml`** + the cross-container test harness.
- [ ] **Fault tolerance + scaling** — graceful degradation (AI / DB down); horizontal scaling (replicas + gunicorn workers) + the **multi-machine path** (Docker Swarm overlay, or `ai` replicas on the Azure VM; **queue-free**) + a locust before/after.
- [ ] **Rate limiting** — flask-limiter on the public routes.
- [ ] **Cross-container tests** — integration (web→ai→db) + system (register→profile→readiness) + **fault-isolation (stop `ai` / stop `db` → web survives)** + stress (locust).
- [ ] **Forum:** the real-time layer (SSE/WebSocket) + notifications + DM transport + media/file storage + the seeding store.
- [ ] **Risk assessment** — anchor the report's "what can go wrong" section (with the team's input).

## You own the decisions
The deploy mechanism, the compose/CI structure, the real-time transport (SSE vs Socket.IO), schema indexes — your call.
