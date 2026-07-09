# Design — Work Smarter, Not Harder

Living technical design. **Spec sources:** the submitted [`PROPOSAL.md`](PROPOSAL.md) (graded 100/100 — the contract)
+ the revised [`PROPOSAL-v2.md`](PROPOSAL-v2.md) (current intent). **Driving rubric:** [`FEEDBACK.md`](FEEDBACK.md).
Items marked *proposed* are confirmed at the kickoff; open decisions are at the bottom; reference the PR that changes a decision.

## Ownership & freedom (how the split works)
The split is **contract-based**: the only fixed, shared things are the **interfaces between containers** — the `/predict` request/response, the Mongo collections (§2), and the `web` ↔ `ai` ↔ `db` boundaries. **Behind its contract, each owner implements their aspect however they want** — the AI owner picks the dataset, model, class binning, and augmentation ([`../ai/README.md`](../ai/README.md)); the web owner picks the auth/session approach + frontend; the DB owner picks schema details + indexes. Constrain a teammate's **contract**, never their **implementation**. (Pairs with the CI-gated self-merge policy — own your scope + its tests — and with course L5.1 modules/interfaces + L8.1 "don't polish teammates' code".)

## 1. Architecture — 3 containers (only `web` exposed)
- **web** — Flask: frontend + auth (werkzeug hashing) + API. Host **8000** → container 5000 (never publish 5000 — macOS AirPlay). The only user-facing container.
- **db** — MongoDB. Internal only; named volume for persistence; healthcheck + `depends_on`.
- **ai** — model inference + recommendation generation. Internal only (`expose`, no host port).

```
User → web ──┬──► ai   (POST /predict, internal)
             └──► db   (mongodb://db:27017, internal)
```

## 2. Data model (MongoDB — PROPOSAL §9)
- `users` — { username *(unique internal handle)*, display_name *(non-unique, shown)*, email, password_hash }
- `profiles` — { user_id, age, gender, height, weight, goal, training_frequency }
- `programs` — { workout programs / exercise catalog }
- `analysis_history` — { user_id, metrics, assessment, calories, timestamp }

## 3. API contracts
| Endpoint | Method | Container | Notes |
|---|---|---|---|
| `/register` `/login` `/logout` | POST | web | werkzeug hashing; session/token; auth-gate decorator |
| `/profile` | GET/POST | web | reads/writes `profiles`; validate input (NoSQL-injection guard) |
| `/predict` | POST | ai (internal) | state assessment + recommendations |

**`web → ai` `POST /predict`** (internal): request `{ features: { sleep_hours, resting_hr, hr_change, fatigue, soreness, weekly_freq, training_load, calorie_balance, bodyweight_trend } }` → response `{ state: <category>, proba: { <category>: <float> }, recommendations: [ … ] }`. *(`recommendations` is a **list** of prioritized action items — each item's content is the AI owner's call. Feature set + category set are candidates, finalized during data exploration.)* The web also reads an **optional `calories`** target from the response and surfaces it on the dashboard (it degrades to `null` when absent); the `ai` includes it once `ai/calories.py` is wired into `/predict`.

## 4. AI decision engine (the heart)
One pipeline, two capabilities:
1. **State assessment** — a supervised classifier (**Random Forest** chosen: ML-course-taught, local, fast, explainable; **swappable** behind the `/predict` contract) → a small set of training-state categories (exact set TBD).
2. **Recommendation generation** — combines the assessment + goals + program + recovery → action plan / workout / program adjustments / calories.

- **Baked into the `ai` image** (`joblib.dump` → `COPY` → `joblib.load`; **pin sklearn** so the pickle loads). Never train/download at runtime.
- **Parallelism & scaling (L7 — required):**
  - *Parallel programming in the code:* processes, not threads (the GIL); plus NumPy **vectorization** in the feature pipeline. The original guidance here — *"a single-row `.predict()` is sub-ms, don't pool that"* — was right on throughput grounds and is now **overridden by the rubric**: `GUIDELINES.md` §2 (+5) requires a queue that works concurrent `/predict` calls in parallel, so the pool sits per-request by mandate. It costs a pickle round-trip per call, which is why the queue is bounded and why `ai` runs one gunicorn worker. Beyond that, `multiprocessing` stays reserved for a genuinely CPU-bound batch (the recommendation engine searching many candidate plans, batch scoring, collaborative-filtering similarity) — measured before/after, never guessed (MiniHW4).
  - *Horizontal scaling:* stateless containers → `docker compose up --scale ai=N` + gunicorn `--workers`; `web`→`ai` round-robins by service DNS (`AI_URL`).
  - *Multiple machines:* containers hold no in-process state, so they scale across hosts via a **Docker Swarm overlay** (`docker stack deploy`) **or** `ai` replicas on the **Azure VM** reached over the network.
  - *Job queue (+5 — required by the current TA guidelines; owner: Elad):* **built** — `ai/jobqueue.py` puts a bounded queue + a `ProcessPoolExecutor` in front of `inference.predict_one`, so concurrent `/predict` calls are worked in parallel rather than serialized. Bounded on purpose: past `AI_QUEUE_MAX_PENDING` it sheds with 503, because an unbounded backlog on the ~1 GB VM is an OOM, not a slowdown. `ai` therefore runs **one** gunicorn worker (its job store is in-memory) with `--threads`; the parallelism is the pool. This supersedes the earlier no-queue guidance — the TA's `WSNH_Guidelines.pdf` now explicitly requires it (see [`GUIDELINES.md`](GUIDELINES.md)).
  - *Concurrency (I/O-bound — the "async" half of the PDF's "async + parallel programming"):* the web tier serves many simultaneous clients via gunicorn workers (async workers optional), and the Forum's real-time layer (SSE/WebSocket) is async.
  - *Proof — measured, not asserted* ([`SCALING_REPORT.md`](SCALING_REPORT.md)): the in-container pool 1→4 gives **2.86×** throughput with p95 halved; `--scale ai=2` gives **1.60×** (Docker service-DNS round-robin). The same experiment on a thread pool scores **0.96×** — the GIL — which is why the pool is processes, and why `test_pool_scaling.py` guards it. Because the shipped model is a microsecond placeholder, the numbers are taken against a CPU-bound stand-in (`ai/bench.py`) in the same seat the Random Forest will occupy; it is never the production target.
  - *Replica caveat:* `ai`'s job store is per-container, so `POST /predict` is replica-safe but `GET /jobs/<id>` is not (the read round-robins to a replica that never saw the job). `web` calls only `/predict`. Making `/jobs` replica-safe means an external store — a 4th container on a 1 GB VM for an endpoint nothing calls.
- Trained on wellness + program-catalog data; any synthetic augmentation (bootstrapping / class-balancing) documented.
- **Dataset · model · binning · augmentation are the AI owner's call** (behind the `/predict` contract). Current starting point: **PMData** (Simula) + Random Forest. Details + open decisions live in [`../ai/README.md`](../ai/README.md).

## 5. Security & fault tolerance
- Hash passwords (werkzeug); auth-gate protected endpoints; rate-limit; validate input; defend NoSQL injection; only `web` exposed.
- **Edge hardening (Caddy + proxy)** — the public Caddy edge sends HSTS, `X-Content-Type-Options: nosniff`, `X-Frame-Options: SAMEORIGIN` + CSP `frame-ancestors 'self'` (clickjacking; same-origin framing kept so the debug mobile-preview works), and `Referrer-Policy`; the app runs behind `ProxyFix(x_for=1)` so the rate limiter keys on the real client IP, not Caddy's internal one. `/ready` returns only `{status}` (no component detail) to anonymous callers.
- **No user-enumeration on the auth flows** — `/login` (identical body + a decoy hash on the user-missing path), `/forgot-password` (identical 200 whether or not the email is registered), and `/register` (on the verify-on path a taken email returns the same `verify_required` response as a fresh one — no code issued, owner emailed a notice) never reveal whether an account exists. *(Verify-off dev/test mode still returns a 409 for a duplicate; see §8.)*
- **Security ownership** (cross-cutting — each layer secures itself, there is no single "security owner"):
  **Lior (web backend + thin data CRUD)** — password hashing (werkzeug), auth-gate, input validation, NoSQL-**injection-safe queries** in the thin `db.py` CRUD (inputs type-validated at the route layer), the auth/login **Security_Tests**.
  **Lior (data layer)** — the Mongo **indexes + `$jsonSchema` validators + auth config + backups + seed** (`ensure_indexes`/`ensure_schema`/`db/seed.py`).
  **Elad (abuse defense + scale)** — **rate-limiting** / anti-spam (flask-limiter), stress / abuse defense.
- **Auth stays stateless / shared-store** (signed token, or a DB/Redis-backed session — not in-process), so `web` can scale to N replicas for the deploy +10 (the big-HW used Bearer tokens). *(web owner's implementation; the scale constraint is shared.)*
- `ai` down → `web` returns "assessment unavailable" (no crash); `db` down → reduced functionality; wearable data missing → manual entry.
- **Fault isolation is *tested*** — system tests **stop the `ai` container** (web still serves, degraded) and **stop `db`** (web still serves, no crash), proving one container going down doesn't take the system down (TA requirement). External calls are wrapped in try/except.

## 6. Testing (the requirement persists — kept out of the spec doc per Noam, tracked here)
All **5 course test types** live in `tests/{Unit,Integration,System,Stress,Security}_Tests/` + a **feature×test matrix** maintained in the repo/report (not in the proposal, per Noam's "this doc is no place for tests"). `TESTING`/`debug` env flags; tests run on any machine (no local paths). CI runs them on every commit; a 0-test run fails.

## 7. Decisions (mini-ADRs)
- **3 containers, only `web` exposed** — course rule; only `web` gets host ports.
- **Local RF, baked into the image** — no runtime train/download; pin sklearn; RF swappable behind `/predict`.
- **F6 + F7 merged** → one "Program Balance & Action Plan" pipeline (analysis feeds prioritization; two capabilities from the user's view). ⚠️ **Pending Noam's email OK** — merging a feature needs his sign-off; the submitted **9-feature** scope is the graded contract until he confirms.
- **Scaling = `ai` replicas + gunicorn workers** (horizontal, measurable with locust); `multiprocessing` only for *measured* CPU-heavy work, not per-request RF inference.

## 8. Open / to confirm
- **F6+F7 merge** — awaiting Noam's reply.
- **Smartwatch import** — stretch; awaiting Noam (Samsung has no web API → likely a real export-file parse).
- **Exact training-state categories + final feature set** — during data exploration.
- **Deploy ordering** (Azure right after MVP vs after the 80) — team decision.
- **Forum real-time layer** (SSE vs Flask-SocketIO) — at Phase 3.
- **Register email-enumeration** *(FIXED — #163, 2026-07-08)* — `/register` used to return a `409 "an account with this email already exists"` for a taken email, disclosing existence (unlike `/login` + `/forgot-password`, §5). **Now non-enumerating on the verify-on path (prod):** a taken email returns the *identical* `verify_required` response as a fresh one — no pending signup is stashed (so no code can complete it) and `_notify_existing_account` emails the owner a "you already have an account — log in or reset" notice instead of a verification code. An attacker who doesn't control the address can't tell taken from free. Verify-off (dev/tests) still returns the plain 409. Tested in `test_register_verify.py`; matches §5. (Originally surfaced by the Round-1 adversarial review, 2026-07-04.)

### Hardening backlog (low-severity; surfaced by the Round-1 adversarial review, 2026-07-04)
- **DM send-rate cap is a soft limit** *(deferred — Elad, anti-spam lane)* — the 20-DM / 60 s cap (`RATE_MAX_PER_WINDOW`) is checked non-atomically (`count_since` then `send`), so a concurrent burst from one user can overshoot by up to (concurrency − 1) messages before the counter catches up. Bounded and low-impact. Fix belongs with the flask-limiter anti-spam layer: enforce it atomically (an atomic insert-and-count, or a `@limiter.limit` on `/messages`) instead of the read-then-act check.
- **Per-recipient email-send cap** *(deferred — Elad, anti-spam lane)* — outbound verification / reset emails are capped **per-IP** (register 10/min, resend 5/min) but not **per-recipient**, so in LIVE-email mode a caller could drive repeated verification emails toward a chosen address (email-bombing), bounded only by the per-IP limit. Fix (anti-spam): a per-recipient sliding-window throttle at the send sites — skip the send over the cap, keep the response identical (no enumeration). Mock mode is unaffected (nothing leaves the box).
- **forgot-password timing side-channel (live mode only)** *(deferred — low)* — `/forgot-password` returns an *identical body* whether or not the email is registered (the primary no-enumeration defense — tested), but the registered branch does a blocking SMTP send while the unregistered branch returns immediately, so in LIVE-email mode response latency is a noisy secondary oracle for "is this email registered?". Fix: send the email off the request thread (fire-and-forget) so both branches return equally fast. Deferred because it conflicts with the current synchronous-send test contract (the reset tests read the captured email right after the request) and the leak is noisy + live-mode-only (negligible in the default log backend).
- **Forum vote 503 under extreme concurrency** — ✅ **FIXED (#150)**: forum votes are now a single atomic aggregation-pipeline update, so a valid vote no longer 503s under many simultaneous voters (was a whole-array CAS retry loop that could exhaust its retries). *(Recorded for history.)*
