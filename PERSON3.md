# PERSON 3 — Elad — infra, deploy, data & the real-time backend

> Your area, the mandatory course items, and a roadmap. How you build it is your call. You own the plumbing that
> runs and ships the app, the **data store** (the **Mongo container** + schema/indexes; the thin CRUD in
> `services/db.py` is Lior's), plus the Forum's real-time backend. `docker-compose.yml` is your starting point.

## Start now — unblocked on day 1
The 3-container skeleton already runs, so you can start the Azure setup, the second compose file, the stress
harness, and the cross-container test harness immediately — none of it waits on the features.

## Your contracts (fixed)
- You own the **Mongo container** (`db` service) + its volume/schema/indexes. The thin CRUD functions in `web/services/db.py` are **Lior's** (already implemented + tested); you provide the running Mongo they connect to. `get_db()` reads `MONGO_URI` — keep the `db` service reachable at that URI.
- Only `web` is exposed (host 8000 → 5000); `ai` + `db` internal.

## Mandatory (course — graded)
- **docker-compose** (the base 3-container file already exists — extend it) — healthchecks, only `web` published (host 8000, never 5000).
- **`docker-compose.test.yml`** — a second compose for the test run (`TESTING=1`).
- **Never commit `.env`** (commit `.env.example`).
- **Rate limiting** (flask-limiter) on the public endpoints; defend against spammers.
- **Stress tests** (locust) — decide in advance what can crash, and defend it.
- **The deploy +10** — Azure deploy + CI auto-deploy on green (the CI gate already runs).

## Roadmap (build these — your way)
- [ ] **Mongo container** — stand up the `db` service with a persistent volume reachable at `MONGO_URI`. The CRUD's **unique indexes** (`users.username`, `forum_posts.id`) already ship in `services/db.py` `ensure_indexes()` (Lior, best-effort on first connect); you add any further **performance/schema indexes** + tuning, plus **container auth** for prod. (The thin CRUD itself is **Lior's** — implemented + tested against a fake.) Once it's up, validate the CRUD against real Mongo: `TEST_MONGO_URI="mongodb://localhost:27017/worksmarter_test" pytest tests/Integration_Tests/test_db_mongo.py` (skips without a DB).
- [ ] **Azure deploy + CI/CD** — extend the live pipeline to deploy on green `main`; scale via `ai` replicas + gunicorn workers. Start early.
- [ ] **Cross-container test harness** — `docker-compose.test.yml` is **scaffolded** (TESTING=1 + a throwaway `worksmarter_test` DB); add the **test-runner service** that runs `pytest` against the live stack (your Dockerfile / how the tests mount into an image).
- [ ] **Fault tolerance + scaling** — graceful degradation (AI / DB down); horizontal scaling (replicas + gunicorn workers) + the **multi-machine path** (Docker Swarm overlay, or `ai` replicas on the Azure VM; **queue-free**) + a locust before/after.
- [ ] **Rate limiting** — flask-limiter on the public routes.
- [ ] **Cross-container tests** — integration (web→ai→db) + system (register→profile→readiness) + **fault-isolation (stop `ai` / stop `db` → web survives)** + stress (locust).
- [ ] **Forum:** the real-time layer (SSE/WebSocket) + notifications + DM transport + media/file storage + the seeding store.
- [ ] **Risk assessment** — anchor the report's "what can go wrong" section (with the team's input).

## You own the decisions
The deploy mechanism, the compose/CI structure, the real-time transport (SSE vs Socket.IO), schema indexes — your call.
