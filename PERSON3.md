# PERSON 3 — Elad — deployment, real-time & scale

> Your area, the mandatory course items, and a roadmap. How you build it is your call. You own what
> **ships, scales, and runs the app live** — taking the Azure deploy + CI/CD pipeline **live** (the pipeline
> *code* is already in the repo — see Lior / [`docs/CICD_REPORT.md`](docs/CICD_REPORT.md)), the cross-container
> test harness, and scaling — plus the Forum's **real-time backend** and rate-limiting.
> `docker-compose.yml` is your starting point.

## Start now — unblocked on day 1
The 3-container skeleton already runs, so you can start the Azure setup, the test-runner service, the
stress harness, and the real-time backend immediately — none of it waits on the features.

## Your contracts (fixed)
- The 3 containers are defined in `docker-compose.yml`; you deploy + run that stack on Azure. The `db`
  service is a stock `mongo:7` — keep it reachable at `MONGO_URI` (the app reads it via `get_db()`). The
  data layer itself (CRUD, indexes, validators, auth config, seed) is Lior's, so you don't configure Mongo.
- Only `web` is exposed (host 8000 → 5000); `ai` + `db` internal.

## Mandatory (course — graded)
- **docker-compose** — the base 3-container file + fault-tolerance are in place; **extend** it with the
  **test-runner service**, the **deploy job**, and **scaling** (replicas/workers). Only `web` published
  (host 8000, never 5000).
- **`docker-compose.test.yml`** — a second compose for the test run (`TESTING=1`).
- **Never commit `.env`** (commit `.env.example`).
- **Rate limiting** (flask-limiter) on the public endpoints; defend against spammers.
- **Stress tests** (locust) — decide in advance what can crash, and defend it.
- **The deploy (+10)** — take the CI/CD pipeline (already in the repo: `ci.yml` `build`+`deploy`, `docker-compose.prod.yml`, `Caddyfile`, auto-rollback, `/ready` gate — PRs #91/#92) **live**. Already done (Lior): the `build` job pushes both images to GHCR, the **GHCR packages are public**, and the `APP_SECRET_KEY`/`SMTP_*` secrets are set. Your part is the **VM**: provision it, set `SSH_PRIVATE_KEY` + `SSH_HOST`, (optional) the `app` CNAME + `SITE_ADDRESS`, add UptimeRobot, and demo an auto-deploy on green `main`. Run-sheet: [`docs/DEPLOY_DEMO.md`](docs/DEPLOY_DEMO.md). Graded on that live demo.

## Roadmap (build these — your way)
- [ ] **Azure deploy + CI/CD (go live)** — the pipeline *code* is written + hardened (Lior, PRs #91/#92:
  build→GHCR→SSH-deploy→Caddy HTTPS + `docker-compose.prod.yml`, auto-rollback, `/ready`), **the GHCR packages are
  already public, and `APP_SECRET_KEY`/`SMTP_*` are already set**. Your part: get the VM from the instructor, set
  `SSH_PRIVATE_KEY` (secret) + `SSH_HOST` (variable), optionally the `app` CNAME + `SITE_ADDRESS` for the branded
  domain, add UptimeRobot (R9), and run the live deploy demo. Steps: [`docs/CICD_REPORT.md`](docs/CICD_REPORT.md)
  + the run-sheet [`docs/DEPLOY_DEMO.md`](docs/DEPLOY_DEMO.md).
- [ ] **Scaling** — horizontal scale (`ai` replicas + gunicorn workers) + the **multi-machine path**
  (Docker Swarm overlay, or `ai` replicas on a second machine; **queue-free**) + a locust before/after.
- [ ] **Cross-container test harness** — `docker-compose.test.yml` is **scaffolded** (TESTING=1 + a
  throwaway `worksmarter_test` DB); add the **test-runner service** that runs `pytest` against the live
  stack (your Dockerfile / how the tests mount into an image).
- [ ] **Cross-container tests** — integration (web→ai→db) + system (register→profile→readiness) +
  **fault-isolation (stop `ai` / stop `db` → web survives)** + stress (locust).
- [ ] **Forum:** the real-time layer (SSE/WebSocket) + notifications + DM transport + media/file storage.
- [ ] **Rate limiting** — flask-limiter on the public routes.
- [ ] **Risk assessment** — anchor the report's "what can go wrong" section (with the team's input).

## You own the decisions
The deploy mechanism, the compose/CI structure, the real-time transport (SSE vs Socket.IO), the scaling
approach — your call.
