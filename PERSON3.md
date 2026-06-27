# PERSON 3 — Elad — infra, deploy & the real-time backend

> Your **area + the mandatory course items + a roadmap** — *not* a step-by-step script. You own the **plumbing that
> makes the app run and ship**, and the Forum's real-time backend. `docker-compose.yml` is your starting point.

## Why you / what changed
You're off the per-feature data work (Lior owns `services/db.py`) — you run the **Mongo container**, not the queries.
And the **CI gate is already live**, so your "CI/CD" is the **deploy half** (Azure), not building CI from scratch.

## Your contracts (fixed)
- You run the **Mongo container** (`db` service); Lior connects via `mongodb://db:27017`.
- Only `web` is exposed (host 8000 → 5000); `ai` + `db` stay internal.

## Mandatory (course — graded)
- **docker-compose** — 3 containers, healthchecks, only `web` published (host 8000, never 5000 — AirPlay).
- **Never commit `.env`** (commit `.env.example`).
- **Rate limiting** (flask-limiter) on the public endpoints.
- **The deploy +10** — **Azure deploy + CI auto-deploy on green** *(the CI gate's 5-pt half already runs)*. Plus **stress tests** (locust).

## Roadmap (build these — your way)
- [ ] **Azure deploy + CI/CD** — extend the live pipeline to deploy on green `main`; public domain; scale via `ai` replicas + gunicorn workers. **Start early** — it has no dependency on the features.
- [ ] **Fault tolerance + scaling** — graceful degradation (AI / DB down) + the replica/worker scaling story.
- [ ] **Rate limiting** — flask-limiter on the public routes.
- [ ] **Cross-container tests** — integration (web→ai→db) + system (register→profile→readiness) + **stress** (locust).
- [ ] **Forum slice (the backend)** — the **real-time layer** (SSE/WebSocket) + live notifications + DM transport + media/file storage + the seeding *store*.

## You own the decisions
The deploy mechanism, the compose/CI structure, the real-time transport (SSE vs Socket.IO), schema indexes — your call. Keep the contracts + mandatory items.
