# Project Report — Work Smarter, Not Harder

**Course:** Writing Software for Machine Learning (00950219), Technion — Spring 2026
**Team:** Shiri Haboob · Lior Ben Sidi · Elad Nachalieli
**Repository:** `LiorBenSidi/work-smarter-not-harder` · **Due:** 23 Aug 2026

> This is the living project report — the 23.08 deliverable required by the guidelines: an explanation of
> the app, a **feature × tests matrix drawn from the real suite**, and a **risk assessment**. It is kept
> in-repo and updated as the build progresses. Spec sources: the submitted [`PROPOSAL.md`](PROPOSAL.md)
> (graded 100/100 — the contract) and the rubric in [`GUIDELINES.md`](GUIDELINES.md) (75 build · +5 Job Queue · +10 Forum ·
> +10 Azure deploy + CI/CD; supersedes [`FEEDBACK.md`](FEEDBACK.md)). Architecture detail lives in [`DESIGN.md`](DESIGN.md); the phased plan in
> [`ROADMAP.md`](ROADMAP.md).
>
> **Last updated:** 2026-07-19 · **Suite at this snapshot:** **1130 tests, 1087 passing / 43 environment-gated**
> (`python -m pytest tests/ -q`; the env-gated ones run in CI's `compose-e2e` job against the live containers).
> Since the 07-12 snapshot (783 tests): **Shiri's Random Forest landed** — a real `ai/model/model.pkl` +
> `inference.py` (exercised by `test_ai_queue_api`), with the readiness recommendation engine and the
> calorie integration + their unit tests — and the suite grew from 783 to 1130 tests.
>
> ⚠️ **Sections still owned by their planes.** §5 (risk), §2's deploy/scale/queue rows and §3's Elad rows are
> current as of this date. §1's API surface + data model now list the DM / SSE / notification / comment-vote
> endpoints and the `messages` / `notifications` collections (**Lior**), plus the media endpoints and the
> `media` collection (**Elad**, #160). §2's core AI rows (F3 model, F4 live value, F7 engine) are **now built**
> (Shiri's Random Forest merged); the **F5 workout-generator / F6 program-balance** wording still awaits
> **Shiri's** confirmation of final scope. The rubric is
> [`GUIDELINES.md`](GUIDELINES.md) (which superseded `FEEDBACK.md` on 8 Jul and added the **+5 Job Queue**).

---

## 1. What the application is

Work Smarter, Not Harder is an AI sports-coaching platform. Instead of only answering *"am I ready to
train?"*, it answers *what to do next, what to improve first, how many calories to eat, whether the program
is balanced, and whether to push, maintain, recover, or deload*. It combines a readiness classifier, a
calorie recommendation, a workout/action-plan engine, a persistent history, and a community forum.

### Architecture — three containers, only `web` exposed

```
                 ┌─────────────────────────── only container with a host port ─┐
   User ──8000──► web (Flask: frontend + auth + API)                            │
                 │        ├──► ai   POST /predict          (internal, no host port)
                 │        └──► db   mongodb://db:27017      (internal, no host port)
                 └───────────────────────────────────────────────────────────────┘
```

- **web** — Flask app: server-rendered SPA frontend, authentication (werkzeug password hashing, CSRF
  double-submit), the JSON API, and orchestration of `ai` + `db`. Publishes host **8000 → container 5000**
  (never 5000 on the host — macOS AirPlay squats there). The only user-facing container.
- **db** — stock `mongo:7`. Internal only; named volume for persistence; healthcheck + `restart`.
- **ai** — model inference + recommendation generation + the calorie engine. Internal only (`expose`, no
  host port).

The seams between containers are the only fixed shared contracts: the `web → ai` `POST /predict`
request/response shape, and the `web → db` data API (`web/services/db.py`). Behind its contract each plane
is implemented independently.

### API surface (implemented)

| Endpoint | Method | Feature |
|---|---|---|
| `/register` · `/login` · `/logout` · `/me` · `/auth/config` | POST/GET | F1 accounts, session, credential hints |
| `/profile` | GET · POST | F2 athlete profile |
| `/checkin` | POST | F3 readiness check-in → `ai /predict` → persist |
| `/dashboard` | GET | F8 dashboard (readiness + recommendations + calories) |
| `/history` | GET | F9 analysis history |
| `/forum/posts` | GET · POST | Forum: list / create |
| `/forum/posts/<id>` | GET · PATCH · DELETE | Forum: read / **edit-own** / **delete-own** (403 otherwise) |
| `/forum/posts/<id>/comments` | POST | Forum: comment |
| `/forum/posts/<id>/vote` | POST | Forum: post vote (strict `+1` / `-1`) |
| `/forum/posts/<id>/comments/<cid>/vote` | POST | Forum: comment vote (strict `+1` / `-1`) |
| `/me/engagement` | GET | Forum: the caller's received-vote totals (§3.3 "personal area" metric; counts only, never voter identities) — **Elad's lane** |
| `/messages` · `/conversations` · `/conversations/<peer>` · `/users/search` | POST · GET | Direct messages: send / list threads / read a thread / recipient search |
| `/notifications` · `/notifications/read` | GET · POST | Notifications feed (poll cursor) + mark-read |
| `/events` | GET | Real-time push — SSE `text/event-stream` (new posts, DMs, notifications) |
| `/media` · `/media/<id>` · `/forum/posts/<id>/attachments` · `/messages/<peer>/attachments` | POST · GET | Media upload / serve + bind-to-post / bind-to-DM (owner/participant-checked) — **Elad's lane (#160)** |
| `/` · `/health` · `/ready` | GET | SPA entry · liveness probe · readiness (dependency) gate |
| `/manifest.webmanifest` · `/sw.js` | GET | PWA install manifest · service worker |
| `ai:/predict` | POST | readiness class + probabilities + recommendations + an optional calorie target (internal; the Random Forest has landed — real inference behind `/predict`) |

### Data model (MongoDB)

`users` { username *(the unique internal handle)*, display_name *(non-unique)*, email, password_hash } · `profiles` { username, age, gender, height, weight, goal,
training_frequency } · `analysis_history` { username, metrics, assessment, calories, timestamp } ·
`forum_posts` { id, author, title, body, anonymous, score, votes, comments } ·
`messages` { id, sender, recipient, body, created_at, read } · `notifications` { id, user, type, text, actor,
read, created_at } · `media` { id, owner, mime, size, target_type, target_id, peers, created_at } *(Elad, #160)*.

---

## 2. Current build status (honest snapshot)

Legend: ✅ done & tested · 🟡 partial / in progress · ⬜ not started. "Plane" is the owning container/aspect,
not a per-line credit — see §6.

| Feature / component | Status | Plane |
|---|---|---|
| F1 — User accounts (register / login / logout, werkzeug hashing, session) | ✅ | web |
| F2 — Athlete profile (validated, injection-safe) | ✅ | web |
| F3 — Readiness analysis — **web path** (check-in → `ai /predict` → persist → surface) | ✅ | web |
| F3 — Readiness analysis — **the model** (Random Forest, real `/predict`) | ✅ merged (`ai/model/model.pkl` + `inference.py`; `test_ai_queue_api` loads the real RF) | ai |
| F4 — Calorie recommendation (Mifflin–St Jeor, `ai/calories.py`) | ✅ engine + unit tests; live value now wired into `/predict` (`calculate_calories` in `predict_one`) | ai |
| F5 — Workout generator | ⬜ (the engine advises on an existing program; a standalone generator is not present — Shiri to confirm scope) | ai |
| F6 — Program-balance analysis (push/pull volume, folds into F7) | 🟡 built in `_program_recommendations`; final scope pending Shiri | ai |
| F7 — Action plan / recommendations — **web surfaces the list**; **engine** | ✅ | web ✅ · ai ✅ (`generate_recommendations`) |
| F8 — Dashboard | ✅ | web |
| F9 — History tracking | ✅ | web |
| Online Forum — CRUD/UI (posts, comments, votes, anonymity, edit/delete-own) | ✅ | web |
| Online Forum — real-time layer (SSE push, DM, vote + DM notifications, media attachments) | ✅ | web (DM/SSE/notifications) · deploy (media, size caps) |
| Online Forum — received-engagement metric (§3.3 per-user vote total: `/me/engagement` + a Profile-screen card) | ✅ | deploy (Elad) |
| Online Forum — cold-seed content | 🟡 (idempotent seed script; content) | web ✅ · ai (content) |
| Data layer — `db.py` CRUD + indexes + `$jsonSchema` validators + auth config + seed + backup | ✅ | web (data) |
| Week-9 observability — named loggers, console + rotating-file handlers, per-request access log | ✅ | web |
| Containers — 3-container `docker-compose`, only `web` exposed, healthchecks | ✅ | web |
| Fault tolerance — restart policies, `start_period`, `web` boots even if `ai` is down; degrade-not-crash | ✅ | web |
| CI gate — ruff → bandit → pytest (+ `mongo:7` service), PR-only branch-protected `main` | ✅ | web (CI) |
| Rate-limiting / anti-spam (flask-limiter) + upload size caps | ✅ | deploy/scale |
| Stress / load (locust + a dependency-free burst) | ✅ | deploy/scale |
| Cross-container test-runner (`docker-compose.test.yml`, CI job `compose-e2e`) | ✅ | deploy |
| Fault isolation — stop `ai` / stop `db`, `web` survives | ✅ | deploy |
| **AI job queue (§2, +5)** — bounded queue + `ProcessPoolExecutor` in front of the model | ✅ | ai (queue) |
| Azure VM deploy + CI/CD auto-deploy | ✅ **live** (`app.worksmarternotharder.dev`; auto-deploy on green `main`, `/ready` gate, auto-rollback) | web (pipeline) · deploy (live) |
| Parallel programming — measured CPU-bound path + horizontal `ai` scaling | ✅ measured: pool 1→4 = **2.86×**, `--scale ai=2` = **1.60×** ([`SCALING_REPORT.md`](SCALING_REPORT.md)) | ai · deploy |

**In one sentence:** the entire web tier, the whole data layer, observability, the 3-container build, and the
CI gate are complete and **proven end-to-end** (a real `web → ai → db` request path, the real-Mongo integration
suite, and in-container logging all verified live); the calorie engine is built + unit-tested and its value is now live in `/predict`, the Random Forest model
has landed (real `ai/model/model.pkl` + `inference.py`), and the deploy / real-time / scale plane are
complete — the remaining work is integration + hardening toward the 23 Aug submission.

---

## 3. Feature × tests matrix (from the real suite)

Every cell names the **actual test file(s)** and count. This supersedes the aspirational Yes/No matrix in
`PROPOSAL.md` §13. The rows below map each graded feature to representative test file(s); the totals under the
table are the **full** suite by type (`pytest --collect-only`).

Columns are the test-type dirs under `tests/`. Cells name representative file(s) + count; the **per-type totals below are exact** (`--collect-only`), and every graded feature has coverage in `tests/` (course rule). Owners: **web / data / CI = Lior · AI model = Shiri · queue / deploy / media / rate-limit = Elad.**

| Feature / component | Unit | Integration | Negative | System / Full-System | Security | Stress |
|---|---|---|---|---|---|---|
| **F1 Accounts / Auth** | `test_auth_validation` (26) · `test_email` (14) | `test_auth_flow` (22) · `test_login_otp` (15) · `test_password_reset` (11) · `test_register_verify` (11) · `test_account_*` (25) | `test_auth_negative` (33) | `test_e2e` leg | `test_auth` (11) · `test_csrf` (6) · `test_debug_email_override` (7) | — |
| **F2 Profile** | `test_profile_validation` (27) | `test_profile_flow` (4) · `test_identity_display` (6) | in `test_profile_checkin_negative` (59) | `test_e2e` leg | `test_profile` (4) | — |
| **F3 Readiness (web path)** | `test_checkin_validation` (31) · `test_ai_client` (3) | `test_checkin_flow` (17) · `test_web_ai` (2) | in `test_profile_checkin_negative` (59) | `test_e2e` leg | — | — |
| **F3 Readiness (model — Shiri)** | `test_ai_inference` (16) · `test_ai_recommendations` (14) · `test_ai_binning` (21) | `test_ai_queue_api` (31, loads the real `model.pkl`) | — | — | — | — |
| **F4 Calorie** | `test_calories` (14) | via `test_checkin_flow` / `test_dashboard_flow` | — | — | — | — |
| **F7 Action plan / recommendations** | (engine covered by the F3-model unit tests) | `test_web_ai` (2) · `test_dashboard_flow` (14) | — | `test_e2e` leg | — | — |
| **F8 Dashboard** | — | `test_dashboard_flow` (14) | — | `test_e2e` leg | `test_dashboard` (2) | — |
| **F9 History** | — | `test_history_flow` (4) | — | `test_e2e` leg | `test_history` (2) | — |
| **Online Forum (CRUD/UI, votes)** | `test_forum_validation` (16) | `test_forum_flow` (18) · `test_comment_votes` (9) | `test_forum_negative` (35) | `test_e2e` leg | `test_forum` (9) | in `test_load` (forum flood) |
| **Forum real-time (DM · notifications · SSE)** | `test_messages_db` (13) | `test_messages` (31) · `test_forum_notifications` (10) | in `test_messages_media_negative` (37) | — | `test_messages_privacy` (5) | — |
| **Forum engagement metric (Elad)** | `test_db_engagement` (7) | `test_engagement` (7) | — | — | — | — |
| **Media (Elad)** | `test_media_store` (3) | `test_media` (11) · `test_elad_lane_journey` (4) | `test_messages_media_negative` (37) | `test_elad_lane_live` (1, live HTTP incl. 10 MB cap) | `test_media_limits` (6) | — |
| **AI job-queue +5 (Elad)** | `test_jobqueue` (43) · `test_bench` (18) | `test_ai_queue_contract` (21) | — | `test_ai_queue_live` (11) | `test_ai_queue` (28) | `test_pool_scaling` (2) · `test_queue_backpressure` (6) |
| **Deploy / scale (Elad)** | — | `test_deploy_contract` (21) · `test_scale_contract` (11) · `test_pin_contract` (4) | — | — | — | — |
| **Rate-limiting / anti-spam (Elad)** | — | — | — | — | `test_rate_limit` (10) | in `test_load` |
| **Data layer (`db.py` + Mongo)** | `test_db` (55) · `test_backup_script` (2) | `test_db_mongo` (22, real Mongo) | — | — | (injection-safe queries) | — |
| **Frontend (SPA / CSRF / a11y / mobile)** | `test_frontend_mobile_guards` (14) | `test_frontend` (71) | — | `test_e2e` leg | `test_csrf` (6) · `test_web_hardening` (4) · `test_review_hardening` (3) | — |
| **Observability (logging)** | `test_logging_config` (19) | — | — | — | (access-log path escaping) | — |
| **App config / debug flag / secret** | `test_config` (13) · `test_scaffold` (4) | — | — | — | (no `.env` tracked) | — |
| **Error handling · ready gate · perf** | — | `test_error_handlers` (5) · `test_ready` (3) · `test_perf` (7) | — | — | — | — |
| **Contract / skeleton / smoke** | — | `test_skeleton_contract` (8) · `test_web_smoke` (1) | — | — | — | — |
| **Fault tolerance / isolation** | — | — | — | `test_fault_isolation` (2) · Full-System `test_parts_in_isolation` (12) | — | — |
| **Whole-system journey** | — | — | — | `test_e2e` (1) · Full-System `test_everything_together_sync` (15) | — | — |

**Totals by type (full suite, `pytest --collect-only`):** Unit **375** · Integration **440** · Negative **164** ·
System **15** · Full-System **27** · Security **97** · Stress **12** → **1130 tests** (`tests/E2E_Tests/` is
currently empty). This matches the header count.

**Pass / skip:** the pre-07-12 snapshot was **747 pass, 36 skip in ~47 s**; the current suite is **1087 pass,
43 skip in ~87 s** (`python -m pytest tests/ -q`). The env-gated skips are *not broken* —
they run the moment their dependency is present:

- `test_db_mongo` (22) — the real-Mongo integration suite; skips without `TEST_MONGO_URI`, and **runs in CI**
  against a `mongo:7` service on every PR.
- `test_ai_queue_live` (11) — the live AI-queue behaviour (bounded queue + process pool over HTTP); runs when
  `AI_BASE_URL` points at the running `ai` container, as CI's `compose-e2e` job does.
- `test_load` (4) — the live-stack stress burst; runs when `E2E_BASE_URL` points at a live stack.
- `test_e2e` + `test_elad_lane_live` (2) — full-stack system journeys; run against a live stack (`E2E_BASE_URL`).
- `test_fault_isolation` (2) — destructive container-stop resilience checks; run with `FAULT_TEST=1`.
- `test_ai` (2) — the original TDD scaffolds for the AI model (Shiri). **Now redundant:** the model has
  landed and its real tests live in `test_ai_inference` / `test_ai_recommendations` / `test_ai_binning`; the
  skipped scaffold should be removed (course rule: don't leave placeholder/skipped tests) — **flagged for Shiri**.

With the live stack up (`TEST_MONGO_URI` + `AI_BASE_URL` + `E2E_BASE_URL` set), the real-Mongo, live-AI-queue,
stress and system-journey suites all execute against the running containers — exactly what CI's `compose-e2e`
job runs green on every PR; only the `test_ai` model scaffolds and the destructive `FAULT_TEST` cases stay gated.

No test is commented-out or `assert True` (course rule: a broken test is deleted or fixed, never muted).

---

## 4. Test strategy — the five course types

The five canonical types live under `tests/{Unit,Integration,System,Stress,Security}_Tests/` (plus
`Negative_Tests/` for adversarial-input coverage and `Full_System_Tests/` for whole-stack journeys), run on any
machine (env vars, no local paths), and are exercised by CI on every PR. A run that collects **0 tests fails** the gate.

- **Unit (375)** — pure functions and single components in isolation: input validators (auth / profile /
  check-in / forum), the calorie formula, the `db.py` CRUD and Mongo-internals logic (against an in-memory
  fake), the logging configuration, and app config. Heavily parametrized on boundary and adversarial inputs
  (e.g. profile validation rejects injection objects, bools-as-numbers, and out-of-range values across every
  field).
- **Integration (441)** — components wired together through the Flask test client: the auth flow, profile
  round-trip, check-in → `ai /predict` → persist, dashboard, history, and the full forum lifecycle. Two
  boundary suites are notable: `test_web_ai` stubs the `web → ai` HTTP seam with a contract-shaped response
  and asserts the dashboard surfaces it (and degrades to `ai_status: unavailable` when `ai` returns
  nothing); `test_db_mongo` runs the data layer against a **real** MongoDB.
- **System (15)** — `test_e2e` drives a complete user journey (register → profile → check-in →
  dashboard → history → forum vote/comment → logout → 401) over HTTP against a live 3-container stack — the
  end-to-end proof that the planes integrate — joined by the live-gated AI-queue, Elad-lane and
  fault-isolation legs that run against the running containers.
- **Stress (12)** — `test_load` is the locust flood scenario (flood posts/votes → expect 429, not a crash;
  live-gated, on demand), plus `test_pool_scaling` and `test_queue_backpressure`, which run per-commit to
  prove the process-pool parallelism and the bounded-queue backpressure hold.
- **Security (97)** — password hashing and session/auth-gating (`test_auth`), CSRF double-submit
  (`test_csrf`), NoSQL-injection-safe queries (`test_profile`, `test_forum`), ownership enforcement on
  forum edit/delete (403), auth-gating of dashboard/history, and response-hardening (`test_web_hardening`).

**How to run**

```sh
pytest -q                                                   # the whole suite (real-Mongo + e2e skip)
TEST_MONGO_URI=mongodb://localhost:27017/worksmarter_test \
  pytest tests/Integration_Tests/test_db_mongo.py           # real-Mongo integration
E2E_BASE_URL=http://localhost:8000 pytest tests/System_Tests # full-stack system journey
```

**CI & verification depth.** CI is ruff → bandit → pytest, plus a `mongo:7` service so the real-Mongo suite
executes on every PR; `main` is branch-protected and PR-only. Beyond CI, the web/data logic added this cycle
was **mutation-tested** (deliberate one-line breakages must be caught by ≥1 test) and reviewed by independent
adversarial passes — the concurrency, logging, fault-tolerance, and Mongo-provisioning paths were hardened
against findings from those passes.

---

## 5. Risk assessment

Fault tolerance is a graded requirement: a dependency failing must **degrade, not crash** the app. Each row
below names a way this system can fail, what the user loses when it does, the mitigation, and — the column
that matters — the **test that would go red if the mitigation were removed**. A mitigation with no test
behind it is an intention, and is marked as such.

A note on how these were chosen. The rows are not a checklist copied from a lecture; each one is either a
failure we induced (stopping containers, flooding the queue, swapping the executor, breaking an invariant to
watch a guard fire) or a failure mode the architecture makes reachable and we chose to bound in advance.
Where a mitigation is deliberately *not* built, the reasoning is given rather than the row being quietly
dropped.

### 5.1 Dependency failure (the mandatory fault-isolation requirement)

| Risk | Impact | Mitigation | Status |
|---|---|---|---|
| **`ai` container down / slow** | No readiness or recommendations | `ai_client` wraps the call in try/except + timeout; the dashboard returns `ai_status: unavailable` and still renders; `web` boots even if `ai` is down (compose `service_started`, not `service_healthy`) | ✅ built & tested (`test_ai_client`, `test_web_ai` degrade case; **`test_fault_isolation.py` stops the real container**) |
| **`db` (Mongo) down** | History can't be read/written | Store calls are try/except-guarded; forum/list routes return 503, not 500; `/health` stays 200 (Mongo-independent) so Docker's healthcheck does not restart a healthy `web`; `/ready` degrades to 503 | ✅ built & tested (`test_fault_isolation.py` stops the real `db` container and re-probes over HTTP) |
| **A restart storm under load** | Cascading outage | `/health` is liveness only — un-rate-limited and Mongo-independent. A 429/5xx there would make Docker + UptimeRobot restart containers *because* they are busy | ✅ built & tested (`locustfile.py` asserts `/health` is always 200 under load) |
| **Email relay (Brevo) down / slow / rate-limited** | OTP + password-reset emails delayed or undelivered | `send_email` wraps SMTP in try/except with a 10 s timeout and **never raises** — a down/slow relay is logged and the flow continues; the code/link stays valid server-side, so login/reset still completes once mail arrives. Free-tier bursts can *delay* delivery (documented: [`EMAIL_DELIVERABILITY.md`](EMAIL_DELIVERABILITY.md)); a rapid re-login now **reuses one valid code** instead of minting many. **The graded path runs locally with no SMTP → codes are surfaced on-screen ([`AUTH_TESTING.md`](AUTH_TESTING.md)), so mail delivery is not on the graded critical path.** | ✅ built & tested (`test_email_smtp_delivery.py`, `test_login_otp_reuse.py`; degrade path in `send_email`) |
| **Wearable / smartwatch data missing** | Advanced metrics absent | Fall back to manually entered values | ✅ by design (no wearable dependency in the core path) |

### 5.2 The AI job queue (GUIDELINES §2) — new surface, new failure modes

Putting a queue and a process pool in front of the model buys parallelism and introduces new ways to
fail. Each is bounded on purpose. (The last two rows came out of the pre-submission adversarial review —
both were real gaps in this table's earlier claims, and both are now guarded by tests that were
mutation-checked by disabling the fix.)

| Risk | Impact | Mitigation | Status |
|---|---|---|---|
| **Queue saturation under a flood** | Unbounded memory growth, and a backlog so deep every caller has already timed out before its job is scored | The backlog is **bounded** (`AI_QUEUE_MAX_PENDING`). Past it `submit()` raises `QueueFull` and `/predict` sheds with **503**, which `web` already treats as "ai unavailable" and degrades. Memory is the lesser reason: a queue deeper than the callers' patience is pure waste — work is done for clients that left. Shedding early keeps the p95 honest, and a bigger VM only moves that cliff, it does not remove it | ✅ built & tested (`test_queue_backpressure.py`: 4× the bound arrives, the excess is shed, `/health` stays 200) |
| **Job-store memory leak** | Slow-fuse OOM: one entry per `/predict`, forever | Finished jobs expire (`AI_JOB_TTL_SECONDS`) and the store is hard-capped (`AI_MAX_JOBS`). TTL alone is insufficient — a burst inside one TTL window is still unbounded — so both exist | ✅ built & tested (`test_jobqueue.py` reaping + cap; `test_queue_backpressure.py` sustained run) |
| **The model raises** | Queue wedges permanently at "full"; every later request 503s | The failure is captured per-job and the depth slot is released on the error path too, so capacity returns the moment the model does. A worker crash cannot kill the callback thread | ✅ built & tested (`test_a_flood_of_failing_jobs_does_not_wedge_the_queue`, `test_one_failing_job_does_not_poison_the_next`) |
| **The model hangs** | A gunicorn thread is pinned forever; `ai` stops serving | `/predict` waits with a bounded timeout (`AI_PREDICT_TIMEOUT_SECONDS`) and returns **504**. The job keeps running — a timeout is the caller giving up, not a cancellation — and the container stays healthy | ✅ built & tested (`test_predict_returns_504_when_the_model_outruns_the_timeout`; verified against the live container) |
| **Backpressure over-admits** | The bound is fiction; the queue exceeds `max_pending` | The depth check and the slot reservation happen under one lock, and `result()` waits on a per-job `settled` event so a caller can never observe a finished job with a stale `pending` count | ✅ built & tested (`test_the_in_flight_depth_never_exceeds_the_bound_under_concurrent_submitters`; `test_stats_are_settled_by_the_time_result_returns` — **this was a real bug, found by a 1-in-3 flake**) |
| **A worker *process* dies (OOM, segfault)** | A `ProcessPoolExecutor` with a dead worker is *permanently* broken: every later `submit()` raises `BrokenProcessPool`, so one crash was a 500 on every `/predict` forever — silently, since `/health` never touches the queue | The queue **self-heals**: a `BrokenProcessPool` (on submit or resolving an in-flight job) replaces the pool, generation-guarded so N concurrent detections rebuild once. The submit is retried once on the fresh pool; the caller whose job died gets a retryable **503**, and the very next request is served normally. Rebuilds are counted in `/queue/stats` (`pool_rebuilds`) | ✅ built & tested (`test_jobqueue.py` broken-pool section; `test_a_dead_worker_process_costs_one_503_not_a_500_forever`) |
| **A worker *hangs* (vs. dies)** | Its future never completes, so its depth slot is never returned; `max_pending` hangs = permanent 503 with no code path back | A hard wall-clock reaper (`AI_JOB_HARD_TIMEOUT_SECONDS`, default 120 s — pinned by a guard test to exceed the `/predict` deadline) **abandons** a job with no result: the slot is released, waiters get a timeout, and a late completion is detected and never double-releases. If *every* pool worker is presumed hung, the pool itself is replaced. Limit honestly stated: Python cannot kill a truly hung worker process from the parent — the stuck process is leaked until the container restarts | ✅ built & tested (`test_jobqueue.py` hung-workers section, incl. the double-release race) |

### 5.3 Scale and deployment

| Risk | Impact | Mitigation | Status |
|---|---|---|---|
| **Load beyond one `ai` worker** | Requests serialize behind the model | Two multiplying axes: the in-container **process pool** (`AI_QUEUE_WORKERS`) and **replicas** (`--scale ai=N`). Measured: **2.86×** and **1.60×** (CPU-bound proxy), and re-measured **directly on the real model** at **~2.5×** and **~1.5×** | ✅ built & **measured on the real model** ([`SCALING_REPORT.md`](SCALING_REPORT.md); `test_pool_scaling.py`) |
| **Someone "simplifies" the process pool to threads** | Silent total loss of parallelism (and the +5): every mocked test still passes | The pool type is asserted, and a real CPU-bound test measures it. A thread pool scores **0.96×** on that test — the GIL — and fails the `>1.5×` bar | ✅ built & tested (`test_pool_scaling.py`, `test_ai_queue_contract.py`) |
| **`GET /jobs/<id>` under `--scale ai=N`** | 404s ~(N−1)/N of the time: the job store is per-container and the GET round-robins to a replica that never saw the job | `web` calls **only** `/predict`, which is replica-safe (one request, one response, nothing read back). Documented in three places and guard-tested | ✅ bounded by design — **not** made replica-safe on purpose: an external store (Redis) would add a 4th container, a new failure mode and a new dependency to serve an endpoint nothing calls (`test_scale_contract.py`) |
| **The CPU-burning benchmark ships as the production model** | Every prediction slow and meaningless | `inference:predict_one` is the default target; a guard asserts no shipped compose file selects `bench:cpu_burn` | ✅ built & tested (`test_scale_contract.py`) |
| **A scaled `ai` gets published to the host** | Port collision on replica 2, **and** an unauthenticated `/jobs` reachable from outside | Only `web` publishes a port, in dev, test, prod and the scale override. `ai` has no auth because nothing but `web` can reach it — that assumption is load-bearing, so it is asserted | ✅ built & tested (`test_deploy_contract.py`, `test_ai_queue_contract.py`, `test_scale_contract.py`) |
| **A bad deploy takes the public site down** | Public app down | CI gates the image build; the build gates the deploy; post-deploy `/ready` is probed over HTTPS and a failure **auto-rolls back** to the previous image while still failing the run. `restart: unless-stopped` survives a VM reboot | ✅ built & tested (`test_deploy_contract.py` locks the pipeline shape; **live** at `app.worksmarternotharder.dev`) |
| **Single Azure VM (no redundancy)** | Total outage if the VM dies | Accepted. The course supplies one VM; the containers are stateless, so a Swarm overlay or a second host is a configuration change, not a rewrite. UptimeRobot alerts on the outage rather than preventing it | 🟡 accepted risk, mitigation documented ([`DESIGN.md`](DESIGN.md) §L7) |
| **Two gunicorn workers on `ai`** | `GET /jobs/<id>` 404s ~half the time — each worker owns a separate in-memory job store, and the read lands on whichever one the OS picked | `ai` runs exactly one worker with threads; parallelism comes from the pool. This is **architectural, not a memory budget** — the 32 GiB VM would host a second worker comfortably, and the job store would still split in two | ✅ built & tested (`test_ai_runs_exactly_one_gunicorn_worker`) |
| **`ai`'s gunicorn worker outlives its own predict deadline** | A `/predict` that runs to `AI_PREDICT_TIMEOUT_SECONDS` races a worker SIGKILL: `web` sees a dropped connection, the in-flight job dies with the process, and the clean 504 degrade is unreachable | gunicorn's `--timeout` (60s) is pinned **above** the queue deadline (30s) in both the image and prod. gunicorn's own default is 30 — equal to the deadline — so leaving it unset was the bug | ✅ built & tested (`test_ai_gunicorn_timeout_exceeds_the_queue_timeout`; guard is mutation-tested against absent *and* too-low values) |

### 5.4 Abuse, security and data

| Risk | Impact | Mitigation | Status |
|---|---|---|---|
| **Spam / request floods (login, register, forum)** | Resource exhaustion, bulk signup, password guessing | `flask-limiter` on the public write routes; messaging carries its own 20/min anti-spam cap. Under load a **429 is the defence engaging**, not a failure — only a 5xx is | ✅ built & tested (`test_rate_limit.py`; `locustfile.py` treats 429 as a pass and 5xx as a failure) |
| **Huge-file upload (posts, comments, DMs)** | Disk exhaustion, memory blowup | Per-upload size caps + type checks; `MAX_CONTENT_LENGTH` rejects an oversized body before Flask parses it | ✅ built & tested (`test_media_limits.py`) |
| **Hostile payload reaching a worker process** | Wasted worker, potential injection | `/predict` validates the body shape and caps the feature count **before** `submit()`, so a rejected request costs a 400, not a pickled round-trip into a child process | ✅ built & tested (`test_ai_queue.py`: injection-shaped keys, feature bombs, oversized bodies) |
| **Job-id enumeration** | Reading another user's readiness score (`ai` has no auth by design) | Job ids are `uuid4` hex, unguessable and non-sequential; an unknown id is a flat 404 with no detail; a model traceback never reaches the caller | ✅ built & tested (`test_ai_queue.py`) |
| **NoSQL injection** | Query manipulation, data leak | All inputs type-validated at the route layer before any query; `db.py` uses parameterized filters, never raw user objects | ✅ built & tested (`test_profile`, `test_forum`, validation unit suites) |
| **Credential theft / weak auth** | Account takeover | werkzeug password hashing (never plaintext); protected endpoints auth-gated; CSRF double-submit on state-changing requests | ✅ built & tested (`test_auth`, `test_csrf`) |
| **Forum abuse — edit/delete others' posts** | Integrity/trust | Ownership check → 403 on non-owner edit/delete | ✅ built & tested (`test_forum`) |
| **Concurrent forum votes / duplicate writes** | Lost updates, double-counts | Optimistic-concurrency (compare-and-set) vote loop with bounded retries; atomic upsert dedupe; TOCTOU-safe edit/delete via matched-count | ✅ built & tested (`test_db`, real-Mongo `test_db_mongo`) |
| **Malformed documents reaching the DB** | Corrupt reads, crashes | `$jsonSchema` validators on all collections (defence-in-depth behind route validation) + unique/perf indexes | ✅ built (`ensure_schema` / `ensure_indexes`), exercised by the real-Mongo IT |
| **Data loss (Mongo volume)** | Irrecoverable history | `db/backup.sh` (gzip dump + retention prune); named volume; fails fast if `MONGO_URI` unset | ✅ built & tested (`test_backup_script`) |
| **Log files growing unbounded** | Disk exhaustion | `RotatingFileHandler` (size-capped, per-worker files); logging fully disableable via env flag | ✅ built & tested (`test_logging_config`) |
| **Secrets committed to the repo** | Credential leak | `.env` git-ignored; `.env.example` only; a scaffold test asserts no `.env` is tracked; the AI model is local → no API keys shipped | ✅ built & tested (`test_scaffold`) |

### 5.5 What we deliberately did not mitigate

Naming these is part of the assessment; an unlisted risk is an unnoticed one.

* **`/jobs` is not replica-safe.** Fixing it means Redis or Mongo-backed job state — a fourth container, a new
  dependency and a new failure mode, serving an endpoint the app does not call. The synchronous `/predict`
  path needs none of it. This was never a memory decision, so the larger VM does not change it.
* **One VM, no failover.** One machine is what the course provides — and it is the single point of failure
  that actually matters. It was resized mid-project to a **Standard E4ads v5 (4 vCPU / 32 GiB)**, which
  bought throughput, not availability. Recovery is `restart: unless-stopped` plus an UptimeRobot alert,
  not redundancy.
* **`web` is not replicated.** Sessions are cookie-signed, so it would scale horizontally, and since the VM
  resize there is RAM to spare for it. We still don't: `web` is I/O-bound (it waits on Mongo and `ai`), so a
  wider **thread** pool inside one gthread worker serves the same concurrency more cheaply than a second
  process, and replicas of `web` on the one VM add no availability — the VM is still the thing that dies.
* **Tail latency across `ai` replicas.** Docker's DNS round-robin balances connections, not work, so p95
  barely improves with replicas. A real load balancer is not warranted for one VM.

### 5.6 How the mitigations are kept honest

Two habits, both visible in the test suite:

1. **Guard tests over prose.** The invariants that a well-meaning future change can silently break — `ai`
   stays internal, the queue stays bounded, the pool stays processes, `/predict` still goes through the
   queue, `predict_one` keeps its shape — are asserted in `test_deploy_contract.py`,
   `test_ai_queue_contract.py` and `test_scale_contract.py`, so the breakage surfaces as a red PR rather
   than as a dead container after a merge.
2. **Mutation testing.** Every guard above was verified by *breaking the invariant on purpose* and
   confirming the guard went red: bypass the queue, swap the pool to threads, unbound the backlog, rename
   `predict_one`, restore a second gunicorn worker, leak the depth counter, delete the reaping, publish an
   `ai` port. A guard that cannot fail is decoration.

The `ai`/`db` fault-isolation requirement, the queue's failure modes, and the web tier's security surface are
covered by tests that run on every PR. The remaining open rows belong to the AI model
(Shiri) and are tracked in [`ROADMAP.md`](ROADMAP.md).

---

## 6. Division of labor (current split)

Roles are **containers/aspects**, not a rigid feature list. The only fixed shared things are the contracts
between planes (§1). Full detail in [`COLLABORATORS.md`](../COLLABORATORS.md) and the `PERSON{1,2,3}.md` files.

| Person | Plane | Owns |
|---|---|---|
| **Shiri** (`shiriHaboob`) | **AI brain** | Random Forest model, real `/predict`, recommendation engine, the dataset, forum cold-seed content; AI unit tests |
| **Lior** (`LiorBenSidi`) | **Web app + data + observability + CI/CD** | Flask backend (API · auth/sessions · validation · ai+db orchestration) + frontend (incl. the Forum **real-time layer — P2P DM · live SSE notifications · vote-notifications · comment-votes**) + the **whole data layer** (`db.py` CRUD, indexes, `$jsonSchema` validators, auth config, backups, seed) + Week-9 logging + the `web`/`ai` container build & compose + the CI gate + the **CI/CD deploy pipeline** (build→GHCR→SSH-deploy→Caddy HTTPS, `docker-compose.prod.yml`); the web/data integration/system/security tests |
| **Elad** (`EladNa1`) | **Live deployment + scale + forum media** | the **live Azure deploy** (VM secrets, GHCR-packages-public, UptimeRobot, the deploy demo — pipeline code is Lior's), the test-runner service, the Forum **media/attachments** (+ file-size caps), rate-limiting (flask-limiter), stress + cross-container tests |

---

## 7. How to run / reproduce

```sh
cp .env.example .env
docker compose up --build          # 3 containers; only web is published
# → http://localhost:8000/health   → then register, set a profile, check in, see the dashboard
pytest -q                          # 1087 pass / 43 env-gated skip
```

CI reproduces the gate on every PR (ruff → bandit → pytest + a `mongo:7` service). `main` is
branch-protected and merges only on green CI.

---

## 8. Open items (tracked; not blockers for the built planes)

- **F6 + F7 merge** — awaiting Noam's confirmation; the submitted 9-feature scope is the graded contract
  until he replies. Fallback (trend-analysis-over-history) is defined in `ROADMAP.md`.
- **Exact readiness categories + final feature set** — finalized by the AI plane during data exploration
  (the `/predict` contract already pins the shapes: features in, `{state, proba, recommendations, calories}`
  out).
- **Deploy ordering** (Azure right after the MVP vs after the 80) and the **forum real-time transport**
  (SSE vs Flask-SocketIO) — deploy/real-time plane decisions.

---

*This report is regenerated against the real suite as the build advances; the matrix in §3 always reflects
`tests/` at the stated snapshot date.*
