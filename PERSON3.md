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
- **The deploy (+10)** — take the CI/CD pipeline (already in the repo: `ci.yml` `build`+`deploy`, `docker-compose.prod.yml`, `Caddyfile`, auto-rollback, `/ready` gate — PRs #91/#92) **live**. Already done (Lior): the `build` job pushes both images to GHCR, the **GHCR packages are public**, and the `APP_SECRET_KEY`/`SMTP_*` secrets are set. Your part is the **VM**: provision it, set `SSH_PRIVATE_KEY` + `SSH_HOST` + `DEPLOY_ENABLED=true` (the deploy runs only when both the host is set and the switch is on), (optional) the `app` CNAME + `SITE_ADDRESS`, add UptimeRobot, and demo an auto-deploy on green `main`. Run-sheet: [`docs/DEPLOY_DEMO.md`](docs/DEPLOY_DEMO.md). Graded on that live demo.

## Roadmap (build these — your way)
- [x] **Azure deploy + CI/CD (go live)** — **done end-to-end**: the deploy is live and auto-deploying on green
  `main` (`https://app.worksmarternotharder.dev`; `SSH_HOST` + `SSH_PRIVATE_KEY` + `DEPLOY_ENABLED=true` set, the
  `app` CNAME + `SITE_ADDRESS` wired, Caddy HTTPS issued); the **graded demo was presented 16 Jul**; the
  **UptimeRobot monitor is live** (R9, monitor `803532626`, 17 Jul). Background below.
  The pipeline *code* is written + hardened (Lior, PRs #91/#92:
  build→GHCR→SSH-deploy→Caddy HTTPS + `docker-compose.prod.yml`, auto-rollback, `/ready`), **the GHCR packages are
  already public, and `APP_SECRET_KEY`/`SMTP_*` are already set**. Your part: get the VM from the instructor, set
  `SSH_PRIVATE_KEY` (secret) + `SSH_HOST` (variable), optionally the `app` CNAME + `SITE_ADDRESS` for the branded
  domain, add UptimeRobot (R9), and run the live deploy demo. Steps: [`docs/CICD_REPORT.md`](docs/CICD_REPORT.md)
  + the run-sheet [`docs/DEPLOY_DEMO.md`](docs/DEPLOY_DEMO.md).
- [x] **Scaling** — measured on both axes ([`docs/SCALING_REPORT.md`](docs/SCALING_REPORT.md)), and since the
  real Random Forest landed, **re-measured against the real model** (#380/#381):
  **vertical** (`AI_QUEUE_WORKERS` 1→4) gives **~2.5×** on the real model (**2.86×** on the CPU-bound proxy);
  **horizontal** (`--scale ai=2`, Docker service-DNS round-robin) gives **~1.54×** real (**1.60×** proxy). The
  two axes multiply. `docker-compose.scale.yml` + `scripts/scaling_benchmark.py` + `LOCUST_TARGET=ai` in the
  locustfile. The proxy workload (`ai/bench.py`) was built when the model was still a contract-shaped
  placeholder returning in microseconds — it would have measured Flask, not the pool; the real-model re-runs
  confirm the proxy was an honest stand-in (within ~13 % on both axes). A thread pool scores **0.96×** on the
  same test — the GIL, and the reason the pool is processes.
  *(Multi-machine Swarm remains a documented path, not a deliverable — one VM.)*
- [x] **Job Queue (+5)** — `ai/jobqueue.py` puts a **bounded** queue + a `ProcessPoolExecutor` in front of
  the model (`ai/inference.py:predict_one`, Shiri's seam), so concurrent `/predict` calls are scored in
  parallel across cores instead of serialized behind the GIL. `POST /predict` keeps its exact shape;
  `POST /jobs` + `GET /jobs/<id>` + `GET /queue/stats` are additive. Past `max_pending` it sheds with 503
  rather than growing a backlog whose callers have already timed out. `ai` runs **one** gunicorn worker (the job
  store is in-memory) with threads. Design: [`docs/JOB_QUEUE_PLAN.md`](docs/JOB_QUEUE_PLAN.md).
- [x] **Cross-container test harness** — `docker-compose.test.yml` now runs a **test-runner service**
  (`tests/Dockerfile`): it waits for `web`+`db` healthy, then drives the live stack over HTTP
  (`E2E_BASE_URL=http://web:5000`) and the throwaway Mongo (`TEST_MONGO_URI`). CI job `compose-e2e`
  runs it on every PR, and `build`→`deploy` depend on it.
- [x] **Cross-container tests** — system (`test_e2e.py`, register→profile→readiness over real HTTP) +
  **fault-isolation** (`System_Tests/test_fault_isolation.py`: stop `ai` / stop `db` → web survives,
  `/ready` degrades to 503) + stress (`Stress_Tests/locustfile.py` + a dependency-free burst in
  `test_load.py`). Deploy/harness invariants are locked by `Integration_Tests/test_deploy_contract.py`.
- [x] **Forum:** media/attachment storage (images/video in posts, comments and DMs) + file-size limits (PR #160).
- [x] **Forum: received-engagement metric** (GUIDELINES §3.3 — "a per-user total in a personal area") —
  `GET /me/engagement` (votes *others* cast on your posts/comments; counts only, no voter identities) +
  a "Community engagement" card on the Profile screen. `forum_received_engagement` in the data layer +
  the seam + the test fake, additive only. *Taken under the team rule (Lior, 10 Jul): unassigned
  responsibilities go to Elad.*
- [x] **Rate limiting** — `flask-limiter` on the public routes (login/register/forum) (PR #160). *(Messaging already has an anti-spam rate-limit — 20/min.)*
- [x] **Risk assessment** — [`docs/REPORT.md`](docs/REPORT.md) §5, rewritten around the question *"which test
  goes red if this mitigation disappears?"*. Five sub-sections: dependency failure · the job queue's four new
  failure modes · scale & deploy · abuse/security/data · **what we deliberately did not mitigate** (`/jobs`
  isn't replica-safe; one VM, no failover; `web` unreplicated; tail latency across replicas). Closes with how
  the guards are kept honest — every one was mutation-tested by breaking its invariant on purpose.

## You own the decisions
The deploy mechanism, the compose/CI structure, the media-storage approach, the scaling
approach — your call. (The DM/notification real-time is done via SSE push — `GET /events` streams
`text/event-stream`; vote notifications can hook straight into the notification feed it pushes.)
