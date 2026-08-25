# Design — Work Smarter, Not Harder

Living technical design. **Spec source:** the revised [`PROPOSAL-v2.md`](PROPOSAL-v2.md) — the 28 Jun version the
TA responded to (**the contract**); the original [`PROPOSAL.md`](PROPOSAL.md) (graded 100/100, 17 Jun) is kept for
history and is **superseded**. **Driving rubric:** [`GUIDELINES.md`](GUIDELINES.md) (which superseded `FEEDBACK.md`).
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

## 2. Data model (MongoDB — as built)
*The shapes below are what the code actually writes. `$jsonSchema` validators cover `users`, `profiles`,
`analysis_history`, `forum_posts`, `messages` and `notifications`; `forum_comments`, `meta` and `media`
carry none.*

- `users` — { username *(unique internal handle)*, display_name *(non-unique, shown)*, email, password_hash }
- `profiles` — { username, **profile**: { age, gender, height, weight, goal, training_frequency } } *(nested)*
- `analysis_history` — { username, **entry**: { timestamp, metrics, assessment, proba, calories, recommendations } } *(nested)*
- `forum_posts` — { id, author, title, body, anonymous, score, votes, **comment_count**, created_at }
- `forum_comments` — { id, post_id, author, body, score, votes, created_at } — comments are their **own**
  documents, keyed by `post_id`, so a hot thread can't grow a post toward Mongo's 16 MB cap (#331)
- `messages` — { id, sender, recipient, body, created_at, read, delivered }
- `notifications` — { id, user, type, text, actor, ref, read, created_at }
- `meta` — { _id: `"forum_rev"`, v } — one monotonic integer bumped by every forum mutation; the SSE stream
  polls it to decide when to push a `forum` event
- `media` — { _id, owner, mime, size, target_type, target_id, peers, created_at } *(`id` is the public
  projection; the stored key is `_id`)* — owned by
  `web/services/media_store.py`, deliberately outside the `db.py` seam (no validator)

> **Not built — deliberately.** The proposal (§9) also specifies a **`programs`** collection to hold the
> program/exercise catalog the workout generator draws on. **F5 shipped without it:** the catalog lives as
> code in `ai/exercise_catalog.py` (99 exercises), versioned with the engine that reads it, so `web` and
> `db` never need to know the exercise list at all. A deviation from v2 §9, recorded in `REPORT.md` §8 (#276).

## 3. API contracts
| Endpoint | Method | Container | Notes |
|---|---|---|---|
| `/register` `/login` `/logout` | POST | web | werkzeug hashing; session/token; auth-gate decorator |
| `/profile` | GET/POST | web | reads/writes `profiles`; validate input (NoSQL-injection guard) |
| `/predict` | POST | ai (internal) | state assessment + recommendations |

**`web → ai` `POST /predict`** (internal): request `{ features: { … } }` → response `{ state: <category>, proba: { <category>: <float> }, recommendations: [ … ], plan: { … } }`. *(`recommendations` is a **list** of prioritized action items — each item's content is the AI owner's call.)*

**As built**, the shipped model consumes **four** features — `sleep_hours`, `fatigue`, `soreness`, `training_load` (`ai/model/model.pkl` `feature_order`) — and returns three categories: `Rest` · `Moderate` · `Ready`. The web sends the full check-in payload; extra keys are ignored by the model. `resting_hr` is collected from the user but is **not** currently a model feature. *(The proposal's candidate list — `hr_change`, `weekly_freq`, `calorie_balance`, `bodyweight_trend` — was explicitly "finalized during data exploration"; those four were not adopted. Enrichment is tracked in #276.)* The web also reads an **optional `calories`** target from the response and surfaces it on the dashboard (it degrades to `null` when absent); the `ai` **does** include it — `ai/inference.py` calls `calculate_calories` and returns it on every prediction.

**`plan`** (F5, #276/#410) is **always present** — unlike `calories`, it never needs a complete profile to produce a safe value. It reads `split_preference`, `training_frequency`, `equipment` and `goal` straight off the request's `features` (the web already merges the athlete's profile into that payload before calling `/predict`, so no extra plumbing was needed on the web side). `ai/workout_plan.py:resolve_split_preference` returns one of two shapes: `{"split": <full_body|upper_lower|push_pull_legs>, "days": null}` when the split is unambiguous, or `{"split_options": [<str>, <str>]}` at 4 or 5 training days/week, where the web is expected to prompt the athlete to choose rather than the engine guessing (agreed with Lior on #410). `predict_one` then fills `days` via `generate_workout_days` when resolved — real exercises drawn from `EXERCISE_CATALOG` (goal shapes sets/reps only, never which exercises are picked); the ambiguous `{"split_options": [...]}` shape is left completely untouched, since there is nothing to generate for a split that hasn't been chosen yet. The dashboard card for `plan` is tracked separately in #410.

**✅ BUILT (#566) — the `web`/`db` producer this described now exists (#276 P7, #528 item 2).** The
undertrained-muscle-group balance analysis (`ai/recommendations.py::_program_recommendations`) is
fully built and unit-tested, but has never had a real input in production: prescribed plan volume
(`generate_workout_days`'s own output) is balanced by construction, so feeding it the plan it just
generated can never fire a real recommendation — confirmed by running the analyser against every
split/frequency combination, not just reading the code. Proposing a new, optional `web → ai`
request field, `features["performed"]`: a flat list `[{"muscle_group": <str>, "sets": <number>},
...]`, the athlete's actual logged training volume per muscle group summed over a **trailing
7-day window** — the same shape `_program_recommendations` already accepts, and a 7-day window so
the analysis's existing weekly thresholds (6–20 sets, chest:back ratio 0.67–1.5) need no
recalibration. `ai/recommendations.py` already reads `features.get("performed")` for this analysis
as of today, and **`web` now sends it**: the athlete's own weekly programme is entered on the profile
(`training_program`, validated in `web/routes/profile.py`) and translated to this exact shape by
`web/services/ai_client.py:build_features` on every prediction — one builder shared by `/checkin`,
the recommendations regen and `/dashboard`, so no call site can be wired and its siblings missed.
Design: `docs/PERFORMED_VOLUME_SPEC.md`, "Option 1" (muscle-group level, no cross-container
dependency on `ai/exercise_catalog.py`).

## 4. AI decision engine (the heart)
One pipeline, two capabilities:
1. **State assessment** — a supervised classifier (**Random Forest** chosen: ML-course-taught, local, fast, explainable; **swappable** behind the `/predict` contract) → one of three training-state categories: **Rest**, **Moderate**, **Ready**.
2. **Recommendation generation** — combines the assessment + goals + program + recovery → action plan / workout / program adjustments / calories.

- **Baked into the `ai` image** (`joblib.dump` → `COPY` → `joblib.load`; **pin sklearn** so the pickle loads). Never train/download at runtime.
- **Parallelism & scaling (L7 — required):**
  - *Parallel programming in the code:* processes, not threads (the GIL). (The feature pipeline itself builds a one-row DataFrame per request — NumPy appears only for NaN handling; single-row inference has nothing to vectorize.) The original guidance here — *"a single-row `.predict()` is sub-ms, don't pool that"* — was right on throughput grounds and is now **overridden by the rubric**: `GUIDELINES.md` §2 (+5) requires a queue that works concurrent `/predict` calls in parallel, so the pool sits per-request by mandate. It costs a pickle round-trip per call, which is why the queue is bounded and why `ai` runs one gunicorn worker. Beyond that, `multiprocessing` stays reserved for a genuinely CPU-bound batch (the recommendation engine searching many candidate plans, batch scoring, collaborative-filtering similarity) — measured before/after, never guessed (MiniHW4).
  - *Horizontal scaling:* stateless containers → `docker compose up --scale ai=N` + gunicorn `--workers`; `web`→`ai` round-robins by service DNS (`AI_URL`).
  - *Multiple machines:* containers hold no in-process state, so they scale across hosts via a **Docker Swarm overlay** (`docker stack deploy`) **or** `ai` replicas on the **Azure VM** reached over the network.
  - *Job queue (+5 — required by the current TA guidelines; owner: Elad):* **built** — `ai/jobqueue.py` puts a bounded queue + a `ProcessPoolExecutor` in front of `inference.predict_one`, so concurrent `/predict` calls are worked in parallel rather than serialized. Bounded on purpose: past `AI_QUEUE_MAX_PENDING` it sheds with 503, because an unbounded backlog grows memory without limit and keeps scoring jobs whose callers have already timed out. `ai` therefore runs **one** gunicorn worker (its job store is in-memory, and a second worker would own a second store) with `--threads`; the parallelism is the pool. This supersedes the earlier no-queue guidance — the TA's `WSNH_Guidelines.pdf` now explicitly requires it (see [`GUIDELINES.md`](GUIDELINES.md)).
  - *Concurrency (I/O-bound — the "async" half of the PDF's "async + parallel programming"):* the web tier serves many simultaneous clients via gunicorn workers (async workers optional), and the Forum's real-time layer (SSE/WebSocket) is async.
  - *Proof — measured, not asserted* ([`SCALING_REPORT.md`](SCALING_REPORT.md)): the in-container pool 1→4 gives **2.86×** throughput with p95 halved; `--scale ai=2` gives **1.60×** (Docker service-DNS round-robin). The same experiment on a thread pool scores **0.96×** — the GIL — which is why the pool is processes, and why `test_pool_scaling.py` guards it. Those headline numbers were taken while the shipped model was still a microsecond placeholder, against a CPU-bound stand-in (`ai/bench.py`) in the same seat; the experiment was **re-run on the real Random Forest** once it landed — **~2.5×** vertical / **~1.54×** horizontal ([`SCALING_REPORT.md`](SCALING_REPORT.md) §"re-measured on the shipped model"). `bench.py` is never the production target.
  - *Replica caveat:* `ai`'s job store is per-container, so `POST /predict` is replica-safe but `GET /jobs/<id>` is not (the read round-robins to a replica that never saw the job). `web` calls only `/predict`. Making `/jobs` replica-safe means an external store — a 4th container, a new dependency and a new failure mode, for an endpoint nothing calls.
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
- **F6 + F7 merged** → one "Program Balance & Action Plan" pipeline (analysis feeds prioritization; two capabilities from the user's view). The source of truth is the TA's [`GUIDELINES.md`](GUIDELINES.md) (`WSNH_Guidelines.pdf`), which permits notified feature changes; the team notified the merge (the 28 Jun v2 proposal). **Not pending anyone** — the balance rule is built (`ai/recommendations.py::_program_recommendations`).
- **Scaling = `ai` replicas + gunicorn workers** (horizontal, measurable with locust); `multiprocessing` only for *measured* CPU-heavy work, not per-request RF inference.
- **Single-file inline frontend** (`web/templates/index.html` — HTML + CSS + JS in one file, ~4k lines). **Why:** zero build step (no bundler/transpiler to configure, break, or explain to a grader), a single deploy artifact Flask serves directly, and the whole SPA is one reviewable/greppable unit. **Tradeoffs (accepted):** no separate CSS/JS lint pass, large diffs on that file, and many guard tests regex the *combined* served HTML. **Mitigation in place:** the E2E "zero uncaught page exceptions" contract (`tests/E2E_Tests/run.mjs`) — every scenario fails if the page raises, which is what actually catches a broken script, and it **gates every PR**. *(A `node --check` syntax gate on the extracted `<script>` was considered and is **not** implemented — the E2E contract covers the same failure at runtime.)* **Planned:** a mechanical `web/static/app.js` + `styles.css` extraction *after* the 16 Jul presentation (a one-shot PR that also re-points the guard regexes) — deliberately **not** before the deadline, since splitting mid-demo-week would force a same-day mass test edit for no functional gain.

## 8. Open / to confirm
- **F6+F7 merge** — in scope (notified per the TA's guidelines); **not pending**.
- **Smartwatch import** — stretch / future work in the proposal; **not a required feature**.
- **Exact training-state categories + final feature set** *(SETTLED — the shipped `model.pkl` bakes them in: features `sleep_hours` · `fatigue` · `soreness` · `training_load`, with the class labels + ready-threshold in the same bundle)*.
- **Deploy ordering** *(SETTLED — deployed early: live on Azure over HTTPS since 8 Jul, redeployed on every merge to `main`)*.
- **Forum real-time layer** *(SETTLED — SSE shipped (`GET /events`, `event: forum` push + the 45s poll backstop); marked ✅ in §2 of this file)*.
- **Register email-enumeration** *(FIXED — #163, 2026-07-08)* — `/register` used to return a `409 "an account with this email already exists"` for a taken email, disclosing existence (unlike `/login` + `/forgot-password`, §5). **Now non-enumerating on the verify-on path (prod):** a taken email returns the *identical* `verify_required` response as a fresh one — no pending signup is stashed (so no code can complete it) and `_notify_existing_account` emails the owner a "you already have an account — log in or reset" notice instead of a verification code. An attacker who doesn't control the address can't tell taken from free. Verify-off (dev/tests) still returns the plain 409. Tested in `test_register_verify.py`; matches §5. (Originally surfaced by the Round-1 adversarial review, 2026-07-04.)

### Hardening backlog (low-severity; surfaced by the Round-1 adversarial review, 2026-07-04)
- **DM send-rate cap is a soft limit** *(deferred — Elad, anti-spam lane)* — the 20-DM / 60 s cap (`RATE_MAX_PER_WINDOW`) is checked non-atomically (`count_since` then `send`), so a concurrent burst from one user can overshoot by up to (concurrency − 1) messages before the counter catches up. Bounded and low-impact. Fix belongs with the flask-limiter anti-spam layer: enforce it atomically (an atomic insert-and-count, or a `@limiter.limit` on `/messages`) instead of the read-then-act check.
- **Per-recipient email-send cap** *(deferred — Elad, anti-spam lane)* — outbound verification / reset emails are capped **per-IP** (register 10/min, resend 5/min) but not **per-recipient**, so in LIVE-email mode a caller could drive repeated verification emails toward a chosen address (email-bombing), bounded only by the per-IP limit. Fix (anti-spam): a per-recipient sliding-window throttle at the send sites — skip the send over the cap, keep the response identical (no enumeration). Mock mode is unaffected (nothing leaves the box).
- **forgot-password timing side-channel (live mode only)** *(deferred — low)* — `/forgot-password` returns an *identical body* whether or not the email is registered (the primary no-enumeration defense — tested), but the registered branch does a blocking SMTP send while the unregistered branch returns immediately, so in LIVE-email mode response latency is a noisy secondary oracle for "is this email registered?". Fix: send the email off the request thread (fire-and-forget) so both branches return equally fast. Deferred because it conflicts with the current synchronous-send test contract (the reset tests read the captured email right after the request) and the leak is noisy + live-mode-only (negligible in the default log backend).
- **Forum vote 503 under extreme concurrency** — ✅ **FIXED (#150)**: forum votes are now a single atomic aggregation-pipeline update, so a valid vote no longer 503s under many simultaneous voters (was a whole-array CAS retry loop that could exhaust its retries). *(Recorded for history.)*
