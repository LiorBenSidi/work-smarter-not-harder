# Build Roadmap — Work Smarter, Not Harder

Phased so we always have a viable product (per Noam's feedback). **Every phase is independently shippable:**
tested, Dockerized, and — once the deploy milestone lands — auto-deployed to Azure on green CI.

**Driving spec:** the submitted [`PROPOSAL.md`](PROPOSAL.md) + the TA's rubric ([`GUIDELINES.md`](GUIDELINES.md),
which supersedes [`FEEDBACK.md`](FEEDBACK.md)):
**75** = the whole app (F1–F9, no stretch goals) on Docker · **+5** Job Queue (parallel AI request handling) · **+10** real-time Forum · **+10** Azure deploy + CI/CD.
Penalties: −5 / bug, −5 / week late. Partial credit per feature; you needn't do it all (this is the bar for a perfect 100).

## Scope decision — pending Noam's OK
**F6 (Program-Balance Analysis) folds into F7 (Action Plan)** as a single rule, rather than a standalone feature:
F7's recommendation engine already surfaces the program-balance insight (e.g. "add chest volume") as a rule
(`ai/recommendations.py::_program_recommendations`) — so F6 need not stand alone. **Note:** F5, the workout
*generator* (a plan from goal + training-days + split), is a **separate proposal feature and is not yet built** —
it is listed under *Complete the 80* below, remains required, and is **not** being swapped.
Emailed Noam to confirm this keeps full credit. **Fallback if he wants a distinct feature:** swap F6 for
*training-trend analysis* over saved history (same data-analysis concept, reuses the history store). Until he
replies, build F6 as a rule inside F7.

## Phase 0 — MVP (must come first)
**Goal:** prove the architecture + the AI heart, end-to-end on Docker.
**Scope:** F1 auth (register / login / logout, werkzeug hashing) · F2 profile · **F3 readiness** (Random Forest
baked into the `ai` image; `web` → `ai` `POST /predict`) · **F4 calorie** (Mifflin-St Jeor, closed-form) · minimal F8 dashboard (readiness + calories) · MongoDB persistence ·
`docker-compose` with 3 containers (only `web` exposed — host **8000** → container 5000).
**Done when:** `docker compose up --build` → register → enter profile → see a readiness class **and a calorie target** on the dashboard;
CI green; first real tests in all five dirs; the feature×test matrix is started; the `debug` flag is wired.

> **Phase 0 vs the proposal's §15 MVP:** Phase 0 is a thin architecture-proving slice. With F4 added it now covers the proposal's §15 "Minimum Working Version" **except the heavier Workout-generator (F5)**, which lands first in *Complete the 80* below — so the full §15 MVP is done by the end of that workstream. **Nothing in the proposal is dropped.**

## After Phase 0 — the workstreams
Order is **open** (recommended as written below; final sequencing TBD). The only hard constraint: **Deploy can't
start until Phase 0 exists** — you can't auto-deploy nothing.

### Deploy + CI/CD (+10) — *recommended next*
**Goal:** every green commit auto-deploys to the supplied Azure VM, publicly.
**Scope:** extend the existing CI (ruff → bandit → pytest) with a deploy job that, on green `main`, redeploys on
Azure; public domain; scale horizontally via gunicorn workers + `ai` replicas (`--scale ai=N`).
**Done when:** a push to `main` → tests pass → the Azure URL serves the update.
*Banks the full +10. The CI-only half (5 pts) is already secured by the existing gate.*

### Complete the 80 — rest of F1–F9
**Scope:** F5 workout generator · **F7 action plan (with F6's balance rule
folded in)** · F9 history · F8 fleshed out (full dashboard + history). Fault tolerance + rate-limiting + input validation + NoSQL-injection
defense across all endpoints.
**Done when:** the whole proposal (minus stretch) runs on Docker; the feature×test matrix is complete; the risk
report is concrete. **= the 80.**

### Job Queue (+5) — Elad ✅ done
**Goal:** the `ai` container handles many concurrent users' requests in parallel, not one at a time.
**Scope:** a **job queue** in front of the model so incoming `/predict` calls are queued and processed in
parallel (worker pool / replicas), rather than serialized per request.
**Done when:** many simultaneous `/predict` calls are accepted and worked in parallel through the queue.

**Shipped:** [`ai/jobqueue.py`](../ai/jobqueue.py) — a **bounded** queue worked by a `ProcessPoolExecutor` in
front of [`ai/inference.py`](../ai/inference.py)`:predict_one`. Processes, not threads: the GIL stops CPU-bound
scoring from overlapping across threads (measured — 0.96× on threads, 3.58× on processes).
`POST /predict` keeps its exact response shape; `POST /jobs` · `GET /jobs/<id>` · `GET /queue/stats` are
additive. Past `AI_QUEUE_MAX_PENDING` it sheds with 503 rather than growing a backlog nobody is still
waiting on. Design: [`JOB_QUEUE_PLAN.md`](JOB_QUEUE_PLAN.md) · numbers: [`SCALING_REPORT.md`](SCALING_REPORT.md).
*Banks the +5. This is the new parallelization requirement in [`GUIDELINES.md`](GUIDELINES.md).*

### Forum (+10) — *built last, in 3 cuttable slices; partial credit accrues per slice*
Same stack as the app (Flask + Mongo + Docker) **plus a real-time layer** — SSE needs no new dependency and
covers one-way feeds/notifications; Flask-SocketIO adds true bidirectional sockets for DM (a dependency →
audit-then-`!`-install when you reach it). All 8 sub-features are needed for the full +10, but Noam gives
**partial credit per feature**, so build hardest-last:

- **3a — Forum content** (backbone): posts (title/body + **image/video** upload) · comments · **anonymity toggle** · **cold-seeding** (seed script: fake accounts/posts/threads) · **rate-limit + file-size caps** (Flask-Limiter + upload validation). Mostly CRUD + uploads + a fixture. → ships a working, seeded forum.
- **3b — Engagement + live feed**: **up/down-votes** on posts+comments · per-user **engagement dashboard** · make the feed **real-time** (introduce the SSE/WebSocket layer here). → ships a live, votable forum.
- **3c — Messaging** (hardest, most cuttable): secure **P2P DM** (text/image/video) · **live notifications** for new DMs + votes (reuses 3b's real-time layer). → ships real-time DM + notifications.

**Tests (each slice):** unit (vote tally · anonymity · size-limit) · integration (post→comment→notify) · security (rate-limit blocks a flood · oversized upload rejected · DM auth-gated + private) · stress (post/vote flood → 429, not a crash).
**Done when:** the slices you ship are integrated, tested, auto-deployed. **Cut line:** if time runs short, 3a (+3b) alone still banks most of the +10 — the app stays a viable 75+10 product without 3c.

## Engineering standards (every phase)
- **TDD-first**; all 5 test types + a feature×test matrix; a broken test is **deleted, not commented out**; tests
  run on any machine (env vars, no local paths).
- **Docker:** ≥3 containers, only `web` exposed (host 8000, never 5000 — macOS AirPlay); RF **baked into the image**
  (joblib, pinned sklearn); **scaling = `ai` replicas + gunicorn workers** (multiprocessing only for measured CPU-heavy work).
- **Security:** hash passwords (werkzeug); auth-gate endpoints; rate-limit; validate input; defend NoSQL injection.
- **Fault tolerance:** an AI / Mongo / wearable failure must degrade, not crash the app.
- **Process:** regular, informative commits from **all 3** members (history is graded); never commit `.env`; repo
  stays outside OneDrive.

## Parallel execution (everyone starts day 1)
The contracts are fixed and stubbed, so the three planes build independently from the first commit — nobody waits:
- **Shiri (`ai/`)** — standalone; builds + tests the model and `/predict` via the test client.
- **Lior (`web/`)** — the web app (against the `/predict` stub) + the `db.py` CRUD & Mongo internals + the container build + the CI gate.
- **Elad (deploy/scale)** — Azure setup + the deploy job, the test-runner service (in `docker-compose.test.yml`), the remaining Forum media/attachments, and the stress + cross-container harness.

The only coordination points are the seams (`/predict` shape, `db.py`'s function API, only-`web`-exposed) — changing one is a **sync point** (flag it in the PR + the group chat).

## Requirements coverage (TA notes + guidelines + Noam's rubric)
| Requirement | Status | Owner |
|---|---|---|
| Docker, runs first-try anywhere | ✅ (web/ai Dockerfiles + compose + fault-tolerance) | Lior |
| ≥3 communicating containers, only `web` exposed | ✅ | Lior |
| Local AI model, baked into image, pinned sklearn | ⬜ | Shiri |
| All 5 test types — per-feature, run-anywhere, no-cheating | 🟡 scaffolds + matrix | all |
| `docker-compose.yml` **and** `docker-compose.test.yml` | ✅ compose + fault-tolerance; the **test-runner service** boots with the stack and drives it over HTTP (CI job `compose-e2e`, gating `build`→`deploy`). Plus `docker-compose.scale.yml` (replicas + workers) | Lior (compose) · Elad (runner, scale) |
| `debug` flag toggles debug mode | 🟡 env wired; confirm it toggles | Lior |
| Password hashing (werkzeug) | ✅ | Lior |
| Input validation (routes) + injection-safe queries (thin `db.py` CRUD) | ✅ | Lior |
| Rate-limit / anti-spam | ✅ messaging 20/min (Lior); `flask-limiter` on the public write routes + upload size caps (#160, Elad). Under load a 429 is the defence engaging, not a failure | Lior (messaging) · Elad (other routes) |
| Fault tolerance + **isolation tested** (stop ai/db → web survives) | ✅ `ai_client` degrades + compose hardening (Lior); `System_Tests/test_fault_isolation.py` stops the real `ai`/`db` containers and re-probes over HTTP — `/health` stays 200, `/ready` degrades to 503 (Elad) | Lior (degrade/compose) · Elad (kill tests) |
| Observability — Week-9 logging (named loggers, handlers, levels, access log) | ✅ web | Lior |
| Parallel programming + scaling — replicas/workers · multi-machine (Swarm / Azure VM) · **job queue for parallel AI requests (+5)** | ✅ **job queue** (`ai/jobqueue.py`: bounded queue + `ProcessPoolExecutor` in front of `inference.predict_one`) and **measured scaling** — pool 1→4 = **2.86×**, `--scale ai=2` = **1.60×**, threads = 0.96× (the GIL). See [`SCALING_REPORT.md`](SCALING_REPORT.md). Multi-machine Swarm stays a documented path (one VM) | Shiri (model) · Elad (scaling + job queue) |
| Stress tests (decide what can crash) | ✅ decided in advance: queue saturation → 503 (never an OOM), auth floods → 429, `/health` always 200 (else a restart storm). `Stress_Tests/{locustfile,test_load,test_queue_backpressure,test_pool_scaling}.py` | Elad |
| GitHub: regular commits from **all 3**, meaningful messages | 🟡 in progress | all |
| Report (app + features×tests + **risk assessment**) | 🟡 [`REPORT.md`](REPORT.md) §5 risk assessment ✅ (rewritten around "which test goes red if this mitigation disappears?", incl. what we deliberately did *not* mitigate). §1 API surface/data model + the AI rows still owed by their owners | all (Elad: risk ✅) |
| Demo video of using the app | ⬜ | all |
| Azure VM deploy + CI/CD auto-deploy (+10) | ✅ **done** — every green `main` auto-deploys to the Azure VM, served over HTTPS at `app.worksmarternotharder.dev` (`/ready` gate + auto-rollback); the graded live **demo was presented 16 Jul** | Lior (pipeline) · Elad (live VM + demo) |
| Online Forum — real-time, 8 sub-features (+10) | 🟡 posts/comments/post-votes + anonymity + edit/delete-own + **P2P DM (text) + live DM notifications (SSE push) + vote notifications + comment votes + anti-spam messaging rate-limit** done; media/attachments + file-size caps done (#160); **received-engagement metric done** (`GET /me/engagement` + a Profile-screen card); open: fuller cold-seeding | Lior (CRUD/UI + DM + notifications + vote-notifs + comment-votes) · Elad (media ✅ #160 · engagement metric ✅) · Shiri (seed content) |
| Present 16 Jul (6 min) · demo by Wk 12 · final 23 Aug | 🟡 presented **16 Jul** ✅; final submission **23 Aug** outstanding | all |
| No shipped API keys | ✅ local model | Shiri |

Legend: ✅ done · 🟡 partial / in-progress · ⬜ not started.

## Status (2026-07-01)
Scaffold + branch-protected PR-only `main` + CI gate (ruff → bandit → pytest, no-false-green) + a local pre-commit
gate are live — that CI already covers the **CI portion** of the deploy requirement.

**Live now:** the runnable 3-container stack (`docker-compose` + healthchecks + gunicorn, only `web` exposed)
with **fault-tolerance hardening** (restart policies, healthcheck `start_period`, `web` boots even if `ai` is
down), the `web↔ai` glue (`ai_client`), the **F4 calorie** function (`ai/calories.py`), and the ratified split.
The **web tier is feature-complete + polished**: auth (**email is the login identity; display names are
non-unique over a stable internal handle**, prefilled from the email prefix) / profile / **daily check-in (F3)** /
dashboard / history / frontend + CSRF + responsive theming + a11y + credential-hint tooltips (`/auth/config`) +
a **distinct visual identity**, Forum CRUD/UI **with edit/delete-your-own**. The **whole data layer** is implemented — the thin
`db.py` CRUD **concurrency-hardened** (atomic dedupe, optimistic-concurrency vote, TOCTOU-safe edit/delete) plus
the Mongo internals (`ensure_indexes` + `$jsonSchema` validators + env-gated auth + `db/seed.py` + `db/backup.sh`),
tested (incl. votes-as-a-list and a real-Mongo integration suite that runs in CI via a `mongo:7` service).
**Week-9 logging** is wired
(named loggers + console/rotating-file handlers + per-request access log). Elad's build lane is **done**: the
`docker-compose.test.yml` test-runner, rate-limiting, the **live** Azure deploy + CI/CD, the job queue, scaling
(measured), Forum media, the received-engagement metric, and the stress/cross-container tests. The Forum
**real-time layer** (SSE, DM, notifications) was built by **Lior** (see the §Forum table above).
**Team rule (Lior, 10 Jul): responsibilities not assigned in writing fall to Elad.** **Still to build:** the
RF model + real `/predict` + recommendation engine + cold-seed content (Shiri). Elad's demo was presented
**16 Jul** and the UptimeRobot monitor went live **17 Jul** (R9) — his lane is complete. Due **23 Aug 2026**.
