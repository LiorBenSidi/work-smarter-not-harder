# Project Report — Work Smarter, Not Harder

**Course:** Writing Software for Machine Learning (00950219), Technion — Spring 2026
**Team:** Shiri Haboob · Lior Ben Sidi · Elad Nachalieli
**Repository:** `LiorBenSidi/work-smarter-not-harder` · **Due:** 23 Aug 2026

> This is the living project report — the 23.08 deliverable required by the guidelines: an explanation of
> the app, a **feature × tests matrix drawn from the real suite**, and a **risk assessment**. It is kept
> in-repo and updated as the build progresses. Spec sources: the submitted [`PROPOSAL.md`](PROPOSAL.md)
> (graded 100/100 — the contract) and the rubric in [`FEEDBACK.md`](FEEDBACK.md) (80 build · +10 Forum ·
> +10 Azure deploy + CI/CD). Architecture detail lives in [`DESIGN.md`](DESIGN.md); the phased plan in
> [`ROADMAP.md`](ROADMAP.md).
>
> **Last updated:** 2026-07-01 · **Suite at this snapshot:** 292 tests, 282 passing / 10 environment-gated.

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
| `/forum/posts/<id>/vote` | POST | Forum: vote (strict `+1` / `-1`) |
| `/` · `/health` | GET | SPA entry · liveness probe |
| `ai:/predict` | POST | readiness class + probabilities + recommendations (internal; web also reads an optional calorie target, added once the model lands) |

### Data model (MongoDB)

`users` { username *(the unique internal handle)*, display_name *(non-unique)*, email, password_hash } · `profiles` { username, age, gender, height, weight, goal,
training_frequency } · `analysis_history` { username, metrics, assessment, calories, timestamp } ·
`forum_posts` { id, author, title, body, anonymous, score, votes, comments }.

---

## 2. Current build status (honest snapshot)

Legend: ✅ done & tested · 🟡 partial / in progress · ⬜ not started. "Plane" is the owning container/aspect,
not a per-line credit — see §6.

| Feature / component | Status | Plane |
|---|---|---|
| F1 — User accounts (register / login / logout, werkzeug hashing, session) | ✅ | web |
| F2 — Athlete profile (validated, injection-safe) | ✅ | web |
| F3 — Readiness analysis — **web path** (check-in → `ai /predict` → persist → surface) | ✅ | web |
| F3 — Readiness analysis — **the model** (Random Forest, real `/predict`) | ⬜ | ai |
| F4 — Calorie recommendation (Mifflin–St Jeor, `ai/calories.py`) | 🟡 engine + 14 unit tests done; live value wires into `/predict` with the model | ai |
| F5 — Workout generator | ⬜ | ai |
| F6 — Program-balance analysis (folds into F7, pending Noam) | ⬜ | ai |
| F7 — Action plan / recommendations — **web surfaces the list**; **engine** | 🟡 | web ✅ · ai ⬜ |
| F8 — Dashboard | ✅ | web |
| F9 — History tracking | ✅ | web |
| Online Forum — CRUD/UI (posts, comments, votes, anonymity, edit/delete-own) | ✅ | web |
| Online Forum — real-time layer (SSE/WebSocket, DM, notifications, media) | ⬜ | deploy/real-time |
| Online Forum — cold-seed content | 🟡 (idempotent seed script; content) | web ✅ · ai (content) |
| Data layer — `db.py` CRUD + indexes + `$jsonSchema` validators + auth config + seed + backup | ✅ | web (data) |
| Week-9 observability — named loggers, console + rotating-file handlers, per-request access log | ✅ | web |
| Containers — 3-container `docker-compose`, only `web` exposed, healthchecks | ✅ | web |
| Fault tolerance — restart policies, `start_period`, `web` boots even if `ai` is down; degrade-not-crash | ✅ | web |
| CI gate — ruff → bandit → pytest (+ `mongo:7` service), PR-only branch-protected `main` | ✅ | web (CI) |
| Rate-limiting / anti-spam (flask-limiter) | ⬜ | deploy/scale |
| Stress / load (locust) | ⬜ | deploy/scale |
| Azure VM deploy + CI/CD auto-deploy | 🟡 pipeline code done (PR #91: build→GHCR→SSH-deploy→Caddy HTTPS); live VM + demo TODO | web (pipeline) · deploy (live) |
| Parallel programming — measured CPU-bound path + horizontal `ai` scaling | 🟡 (plan in DESIGN §4) | ai · deploy |

**In one sentence:** the entire web tier, the whole data layer, observability, the 3-container build, and the
CI gate are complete and **proven end-to-end** (a real `web → ai → db` request path, the real-Mongo integration
suite, and in-container logging all verified live); the calorie engine is built + unit-tested but its value
goes live once the model wires it into `/predict`, and the Random Forest model and the deploy / real-time /
scale plane are the remaining build.

---

## 3. Feature × tests matrix (from the real suite)

Every cell names the **actual test file(s)** and count. This supersedes the aspirational Yes/No matrix in
`PROPOSAL.md` §13 — it is generated from the real `tests/` tree (`pytest --collect-only`), not planned.

| Feature / component | Unit | Integration | System | Stress | Security |
|---|---|---|---|---|---|
| **F1 Accounts / Auth** | `test_auth_validation` (24) | `test_auth_flow` (15) | `test_e2e` leg | — | `test_auth` (11) · `test_csrf` (6) |
| **F2 Profile** | `test_profile_validation` (27) | `test_profile_flow` (4) | `test_e2e` leg | — | `test_profile` (4) |
| **F3 Readiness (web path)** | `test_checkin_validation` (25) · `test_ai_client` (3) | `test_checkin_flow` (5) · `test_web_ai` (2) | `test_e2e` leg | ⬜ *(planned — locust)* | — |
| **F3 Readiness (model)** | `test_ai` (2, ⏸ scaffold) | — | — | — | — |
| **F4 Calorie** | `test_calories` (14) | via `test_checkin_flow` / `test_dashboard_flow` | — *(value surfaces with the model)* | — | — |
| **F7 Action plan (web surfaces list)** | — | `test_web_ai` (2) · `test_dashboard_flow` (5) | `test_e2e` leg | — | — |
| **F8 Dashboard** | — | `test_dashboard_flow` (5) | `test_e2e` leg | — | `test_dashboard` (2) |
| **F9 History** | — | `test_history_flow` (3) | `test_e2e` leg | — | `test_history` (2) |
| **Online Forum (CRUD/UI)** | `test_forum_validation` (16) | `test_forum_flow` (11) | `test_e2e` leg | ⬜ *(planned — flood → 429)* | `test_forum` (9) |
| **Data layer (`db.py` + Mongo)** | `test_db` (36) · `test_backup_script` (2) | `test_db_mongo` (6, real Mongo) | — | — | (injection-safe queries, in `test_profile`/`test_forum`) |
| **Frontend (SPA / CSRF / a11y)** | — | `test_frontend` (12) | `test_e2e` leg | — | `test_csrf` (6) · `test_web_hardening` (4) |
| **Observability (logging)** | `test_logging_config` (19) | — | — | — | (access-log path escaping, in `test_logging_config`) |
| **App config / debug flag / secret** | `test_config` (8) | — | — | — | `test_web_hardening` (4) |
| **Contract / skeleton / smoke** | `test_scaffold` (4) | `test_skeleton_contract` (8) · `test_web_smoke` (1) | `test_e2e` (1) | — | — |
| **Whole-system journey** | — | — | `test_e2e` (register→profile→check-in→dashboard→history→forum→logout) | — | — |
| **Load / abuse** | — | — | — | `test_load` (1, ⏸ locust scaffold) | — |

**Totals by type:** Unit **180** · Integration **72** · System **1** · Stress **1** · Security **38** →
**292 tests**.

**Pass / skip:** locally **282 pass, 10 skip in ~6 s**. The 10 skips are *environment-gated, not broken* —
they run the moment their dependency is present:

- `test_db_mongo` (6) — the real-Mongo integration suite; skips without `TEST_MONGO_URI`, and **runs in CI**
  against a `mongo:7` service on every PR.
- `test_e2e` (1) — the full-stack system journey; runs when `E2E_BASE_URL` points at a live stack.
- `test_ai` (2) and `test_load` (1) — TDD scaffolds for the owners still building those planes (the AI
  model and the locust load scenario); they fail loudly (`NotImplementedError`) once un-skipped, so they
  can't rot into false green.

With the live stack up (`E2E_BASE_URL` + `TEST_MONGO_URI` set), the real-Mongo IT and the system e2e execute
against the running containers too — **289 pass / 3 skip** (only the unwritten AI-model and locust scaffolds
stay skipped).

No test is commented-out or `assert True` (course rule: a broken test is deleted or fixed, never muted).

---

## 4. Test strategy — the five course types

All five live under `tests/{Unit,Integration,System,Stress,Security}_Tests/`, run on any machine (env vars,
no local paths), and are exercised by CI on every PR. A run that collects **0 tests fails** the gate.

- **Unit (180)** — pure functions and single components in isolation: input validators (auth / profile /
  check-in / forum), the calorie formula, the `db.py` CRUD and Mongo-internals logic (against an in-memory
  fake), the logging configuration, and app config. Heavily parametrized on boundary and adversarial inputs
  (e.g. profile validation rejects injection objects, bools-as-numbers, and out-of-range values across every
  field).
- **Integration (72)** — components wired together through the Flask test client: the auth flow, profile
  round-trip, check-in → `ai /predict` → persist, dashboard, history, and the full forum lifecycle. Two
  boundary suites are notable: `test_web_ai` stubs the `web → ai` HTTP seam with a contract-shaped response
  and asserts the dashboard surfaces it (and degrades to `ai_status: unavailable` when `ai` returns
  nothing); `test_db_mongo` runs the data layer against a **real** MongoDB.
- **System (1, + live legs)** — `test_e2e` drives a complete user journey (register → profile → check-in →
  dashboard → history → forum vote/comment → logout → 401) over HTTP against a live 3-container stack. It is
  the end-to-end proof that the planes integrate.
- **Stress (1 scaffold)** — `test_load` is the placeholder for a locust scenario (flood posts/votes → expect
  429, not a crash), owned by the deploy/scale plane; runs on demand, not per-commit.
- **Security (38)** — password hashing and session/auth-gating (`test_auth`), CSRF double-submit
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

Fault tolerance is a graded requirement: a dependency failing must **degrade, not crash** the app. The table
records each risk, its mitigation, and whether that mitigation is **built & tested** today or **planned**.

| Risk | Impact | Mitigation | Status |
|---|---|---|---|
| **`ai` container down / slow** | No readiness or recommendations | `ai_client` wraps the call in try/except + timeout; the dashboard returns `ai_status: unavailable` and still renders; `web` boots even if `ai` is down (compose `service_started`, not `service_healthy`) | ✅ built & tested (`test_ai_client`, `test_web_ai` degrade case; compose hardening) |
| **`db` (Mongo) down** | History can't be read/written | Store calls are try/except-guarded; forum/list routes return 503 with a clear error instead of 500; `web` stays up | ✅ built (route guards); 🟡 kill-container isolation test planned (deploy plane) |
| **Concurrent forum votes / duplicate writes** | Lost updates, double-counts | Optimistic-concurrency (compare-and-set) vote loop with bounded retries; atomic upsert dedupe; TOCTOU-safe edit/delete via matched-count | ✅ built & tested (`test_db`, real-Mongo `test_db_mongo`) |
| **NoSQL injection** | Query manipulation, data leak | All inputs type-validated at the route layer before any query; `db.py` uses parameterized filters, never raw user objects | ✅ built & tested (`test_profile`, `test_forum`, validation unit suites) |
| **Credential theft / weak auth** | Account takeover | werkzeug password hashing (never plaintext); protected endpoints auth-gated; CSRF double-submit on state-changing requests | ✅ built & tested (`test_auth`, `test_csrf`) |
| **Forum abuse — edit/delete others' posts** | Integrity/trust | Ownership check → 403 on non-owner edit/delete | ✅ built & tested (`test_forum`) |
| **Spam / request floods** | Resource exhaustion | Rate-limiting (flask-limiter) + upload size caps | ⬜ planned (deploy/scale plane) |
| **Load beyond one `ai` replica** | Slow responses under concurrency | Stateless containers → `--scale ai=N` + gunicorn workers; locust before/after proof | 🟡 plan in DESIGN §4; ⬜ locust + scaling not yet built (deploy plane) |
| **Data loss (Mongo volume)** | Irrecoverable history | `db/backup.sh` (gzip dump + retention prune); named volume; fails fast if `MONGO_URI` unset | ✅ built & tested (`test_backup_script`) |
| **Malformed documents reaching the DB** | Corrupt reads, crashes | `$jsonSchema` validators on all collections (defense-in-depth behind route validation) + unique/perf indexes | ✅ built (`ensure_schema` / `ensure_indexes`), exercised by real-Mongo IT |
| **Log files growing unbounded** | Disk exhaustion | `RotatingFileHandler` (size-capped, per-worker files); logging fully disableable via env flag | ✅ built & tested (`test_logging_config`) |
| **Secrets committed to the repo** | Credential leak | `.env` git-ignored; `.env.example` only; a scaffold test asserts no `.env` is tracked; local AI model → no API keys shipped | ✅ built & tested (`test_scaffold`) |
| **Deploy unavailability (single Azure VM)** | Public app down | Restart policies (`unless-stopped`, survive reboot); horizontal scaling design; CI-gated auto-deploy on green `main` | 🟡 pipeline built (PR #91); live VM + demo pending |
| **Wearable / smartwatch data missing** | Advanced metrics absent | Fall back to manually entered values (stretch feature; core app is independent of it) | ✅ by design (no wearable dependency in the core path) |

The mitigations already **tested** cover the mandatory fault-isolation requirement for the `ai` and `db`
dependencies and the security surface of the web tier; the outstanding rows belong to the deploy/scale plane
and the AI model, and are tracked in [`ROADMAP.md`](ROADMAP.md).

---

## 6. Division of labor (current split)

Roles are **containers/aspects**, not a rigid feature list. The only fixed shared things are the contracts
between planes (§1). Full detail in [`COLLABORATORS.md`](../COLLABORATORS.md) and the `PERSON{1,2,3}.md` files.

| Person | Plane | Owns |
|---|---|---|
| **Shiri** (`shiriHaboob`) | **AI brain** | Random Forest model, real `/predict`, recommendation engine, the dataset, forum cold-seed content; AI unit tests |
| **Lior** (`LiorBenSidi`) | **Web app + data + observability + CI/CD** | Flask backend (API · auth/sessions · validation · ai+db orchestration) + frontend + the **whole data layer** (`db.py` CRUD, indexes, `$jsonSchema` validators, auth config, backups, seed) + Week-9 logging + the `web`/`ai` container build & compose + the CI gate + the **CI/CD deploy pipeline** (build→GHCR→SSH-deploy→Caddy HTTPS, `docker-compose.prod.yml`); the web/data integration/system/security tests |
| **Elad** (`EladNa1`) | **Live deployment + real-time + scale** | the **live Azure deploy** (VM secrets, GHCR-packages-public, UptimeRobot, the deploy demo — pipeline code is Lior's), the test-runner service, the Forum real-time layer (notifications / DM / media), rate-limiting (flask-limiter), stress + cross-container tests |

---

## 7. How to run / reproduce

```sh
cp .env.example .env
docker compose up --build          # 3 containers; only web is published
# → http://localhost:8000/health   → then register, set a profile, check in, see the dashboard
pytest -q                          # 282 pass / 10 env-gated skip
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
