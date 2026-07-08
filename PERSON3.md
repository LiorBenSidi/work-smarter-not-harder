# PERSON 3 — Elad — deployment, scale & Forum media

> Your area, the mandatory course items, and a roadmap. How you build it is your call. You own what
> **ships, scales, and runs the app live** — taking the Azure deploy + CI/CD pipeline **live** (the pipeline
> *code* is already in the repo — see Lior / [`docs/CICD_REPORT.md`](docs/CICD_REPORT.md)), the cross-container
> test harness, and scaling — plus the remaining Forum **media/attachments**.
> `docker-compose.yml` is your starting point. *(P2P DM (text) + live DM notifications are already built — see
> [`PERSON2.md`](PERSON2.md) / [`docs/ROADMAP.md`](docs/ROADMAP.md); vote notifications are built too, so the
> notification feed is already in place for media to hook into.)*

## Start now — unblocked on day 1
The 3-container skeleton already runs, so you can start the Azure setup, the test-runner service, the
stress harness, and the remaining Forum media/attachments immediately — none of it waits on the features.

**Running the app · live email (optional):** the stack runs fully in **mock mode with zero secrets** (codes show
on screen) — all you need for normal work. To send *real* email locally, get the `.env` from **Lior** over a
private channel (AirDrop / DM) → drop it in your repo root → `docker compose up --build`. It's gitignored —
never commit it. (The GitHub-side secrets for the deploy are in [`SECRETS.md`](SECRETS.md) §3 — your lane.)

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
  (Docker Swarm overlay, or `ai` replicas on a second machine) + a locust before/after.
- [ ] **Job Queue (+5)** — a job queue in front of the model so the `ai` container handles many users'
  `/predict` calls at once, processed in parallel (the new parallelization requirement — [`docs/GUIDELINES.md`](docs/GUIDELINES.md)).
- [x] **Cross-container test harness** — `docker-compose.test.yml` now runs a **test-runner service**
  (`tests/Dockerfile`): it waits for `web`+`db` healthy, then drives the live stack over HTTP
  (`E2E_BASE_URL=http://web:5000`) and the throwaway Mongo (`TEST_MONGO_URI`). CI job `compose-e2e`
  runs it on every PR, and `build`→`deploy` depend on it.
- [x] **Cross-container tests** — system (`test_e2e.py`, register→profile→readiness over real HTTP) +
  **fault-isolation** (`System_Tests/test_fault_isolation.py`: stop `ai` / stop `db` → web survives,
  `/ready` degrades to 503) + stress (`Stress_Tests/locustfile.py` + a dependency-free burst in
  `test_load.py`). Deploy/harness invariants are locked by `Integration_Tests/test_deploy_contract.py`.
- [x] **Forum:** media/attachment storage (images/video in posts, comments and DMs) + file-size limits (PR #160).
- [x] **Rate limiting** — `flask-limiter` on the public routes (login/register/forum) (PR #160). *(Messaging already has an anti-spam rate-limit — 20/min.)*
- [ ] **Risk assessment** — anchor the report's "what can go wrong" section (with the team's input).

## You own the decisions
The deploy mechanism, the compose/CI structure, the media-storage approach, the scaling
approach — your call. (The DM/notification real-time is done via SSE push — `GET /events` streams
`text/event-stream`; vote notifications can hook straight into the notification feed it pushes.)
