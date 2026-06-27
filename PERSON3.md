# PERSON 3 — Elad — infra, deploy & the real-time backend

> Your area, the mandatory course items, and a roadmap. How you build it is your call. You own the plumbing that
> runs and ships the app, plus the Forum's real-time backend. `docker-compose.yml` is your starting point.

## Start now — unblocked on day 1
The 3-container skeleton already runs, so you can start the Azure setup, the second compose file, the stress
harness, and the cross-container test harness immediately — none of it waits on the features.

## Your contracts (fixed)
- You run the **Mongo container** (`db` service); `web` connects via `mongodb://db:27017`.
- Only `web` is exposed (host 8000 → 5000); `ai` + `db` internal.

## Mandatory (course — graded)
- **docker-compose** — 3 containers, healthchecks, only `web` published (host 8000, never 5000).
- **`docker-compose.test.yml`** — a second compose for the test run (`TESTING=1`).
- **Never commit `.env`** (commit `.env.example`).
- **Rate limiting** (flask-limiter) on the public endpoints; defend against spammers.
- **Stress tests** (locust) — decide in advance what can crash, and defend it.
- **The deploy +10** — Azure deploy + CI auto-deploy on green (the CI gate already runs).

## Roadmap (build these — your way)
- [ ] **Azure deploy + CI/CD** — extend the live pipeline to deploy on green `main`; scale via `ai` replicas + gunicorn workers. Start early.
- [ ] **`docker-compose.test.yml`** + the cross-container test harness.
- [ ] **Fault tolerance + scaling** — graceful degradation (AI / DB down); the replica/worker scaling story.
- [ ] **Rate limiting** — flask-limiter on the public routes.
- [ ] **Cross-container tests** — integration (web→ai→db) + system (register→profile→readiness) + stress (locust).
- [ ] **Forum:** the real-time layer (SSE/WebSocket) + notifications + DM transport + media/file storage + the seeding store.
- [ ] **Risk assessment** — anchor the report's "what can go wrong" section (with the team's input).

## You own the decisions
The deploy mechanism, the compose/CI structure, the real-time transport (SSE vs Socket.IO), schema indexes — your call.
