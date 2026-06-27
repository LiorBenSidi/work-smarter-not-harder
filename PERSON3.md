# PERSON 3 — Elad — infrastructure, data & deployment

> Your **area + mandatory course items + a roadmap**. *Not* a step-by-step script — how you build it is yours.
> You own the **plumbing that makes the app run and ship**: Docker, MongoDB, and the +10 deploy.

## Your area, plainly
You own how the three containers run together, the database, the cross-cutting security middleware, and getting
the app onto Azure with auto-deploy. `docker-compose.yml` + `web/services/db.py` are your starting points.

## Your contracts (fixed)
- The **Mongo collections** `users / profiles / programs / analysis_history` (DESIGN §2) — Shiri's routes call your `services/db.py`.
- Only `web` is exposed (host 8000 → 5000); `ai` + `db` internal.

## Mandatory (course — graded)
- **docker-compose** — the 3 containers, healthchecks, only `web` published (host 8000, never 5000 — macOS AirPlay).
- **Never commit `.env`** (commit `.env.example`).
- **Rate limiting** (flask-limiter) — anti-spam on the public endpoints.
- **The +10** — **CI/CD that auto-deploys to Azure on green** (the CI half = 5 pts already runs). Plus **stress tests** (locust).
- **Tests**: integration (write + read a profile) + system (register → profile → readiness end-to-end) + stress.

## Roadmap (build these — your way)
- [ ] **MongoDB** — implement `services/db.py` (connection + the collections); validate inputs.
- [ ] **docker-compose** — flesh out as the app grows (it's wired; add what's needed).
- [ ] **Rate limiting** — flask-limiter on the public routes.
- [ ] **Azure deploy + CI/CD** — extend the pipeline to deploy on green (the second +5 of the deploy points).
- [ ] **Stress tests** — locust against `/predict` and the auth routes.

## You own the decisions
Schema details + indexes, the deploy mechanism, how you structure the compose/CI — your call. Keep the contracts + mandatory items.
