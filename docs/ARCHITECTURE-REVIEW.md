# Architecture Review — Work Smarter, Not Harder

**Type:** design validation (pre-build) · **Date:** 2026-06-27 *(with inline resolutions added through 2026-08-28)* · **Status:** advisory — changes **no** contract.
**Lenses:** system-design · architecture (ADR) · code-review · testing-strategy.
**Validated against:** [`PROPOSAL-v2.md`](PROPOSAL-v2.md) — the 28 Jun revision the TA responded to (**the contract**) · [`PROPOSAL.md`](PROPOSAL.md) (graded 100/100, 17 Jun — superseded, kept for history) ·
the rubric [`GUIDELINES.md`](GUIDELINES.md) (75 + 5 (Job Queue) + 10 + 10; supersedes [`FEEDBACK.md`](FEEDBACK.md)) · the WSML course rules · the live skeleton (`docker-compose.yml`, `web/`, `ai/`, `tests/`).

**Resolution (2026-06-27):** findings **3, 4, 5, 6** are fixed in the follow-up PR — scaling story corrected to replicas + workers; auth-scale note added; the `/predict` shape pinned (`recommendations` is a list, key is `state`); the contract test made behavioural. **1** shipped (SSE feeds/chat/notifications + a media volume); **2** resolved under the v2 spec — all six findings are now closed; the app is built and deployed. **7** is now **live** — the deploy job (GHCR build/push → SSH-deploy-to-Azure → Caddy HTTPS + auto-rollback) is in `ci.yml` and auto-deploys every green `main` to `app.worksmarternotharder.dev` (Elad's go-live step, done; the graded demo run remains); **8** (`/predict` 400-vs-5xx) lands with the model.

## Verdict
The 3-container design is **sound for the 75-point app and the CI half of the deploy +10** — the seams are real,
enforced by tests, and AirPlay-safe. **The team can start building.** But two architecture decisions are still
unfaced and they *ripple into the `web` container's runtime*, so decide them **before** the code they touch lands —
not at Phase 3: **(1) the Forum's real-time + media-storage layer**, and **(2) stateless auth for horizontal scale**.
Separately, one proposal-scope item — **cutting the 5 readiness classes to ~3 / dropping "Injury Risk"** — is the
*same kind of change* as the F6+F7 merge and needs the *same Noam sign-off* (or a zero-cost workaround). Details below.

## What's sound (keep it)
- **Container split & exposure** — only `web` publishes a host port (`8000:5000`); `ai`+`db` are `expose`-only, and
  `Integration_Tests/test_skeleton_contract.py` enforces it. Meets "≥3 communicating containers, only `web` exposed"
  and dodges the macOS-AirPlay-on-5000 trap. (`docker-compose.yml`)
- **Startup ordering** — healthchecks on all 3 + `depends_on: service_healthy`; `web` won't serve before `ai`/`db`
  are ready. (`docker-compose.yml`)
- **Production server** — `gunicorn` in both app containers (not the Flask dev server). (`web/Dockerfile`, `ai/Dockerfile`)
- **Model-bake discipline** — `ai/Dockerfile` documents joblib-bake + pin-sklearn (the Mini-HW2 lesson); no runtime
  train/download. (`ai/Dockerfile`, `ai/requirements.txt`)
- **Fault tolerance is wired, not just promised** — `ai_client.predict()` catches `RequestException` → logs → returns
  `None`, so the caller degrades and the app can't crash on an AI outage. (`web/services/ai_client.py`)
- **No hardcoded secrets** — env-driven config; compose makes `SECRET_KEY` mandatory (`${SECRET_KEY:?…}`). (`web/config.py`, `docker-compose.yml`)
- **Security deps present up front** — `werkzeug` (hashing) + `flask-limiter` (rate-limit) + `pymongo`. (`web/requirements.txt`)
- **Contract-based ownership** — fixed seams + implementation freedom; matches L5.1 interfaces + L8.1 "don't polish
  teammates' code". (`docs/DESIGN.md`)
- **The test gate is load-bearing** — 5 type-dirs; real contract tests enforce the seams now; CI **fails on 0 collected
  tests** (no false-green). (`tests/README.md`, `.github/workflows/ci.yml`)

## Findings

| # | Sev | Area | Issue | Fix — before the code it touches |
|---|---|---|---|---|
| 1 | ✅ | Forum (+10) | The architecture covers only the 75-pt app. The Forum's **mandatory real-time** feeds/chat/notifications (`FEEDBACK.md:61`) and **image/video** storage have **no home** — deferred to "Phase 3" (`DESIGN.md:63`). Transport choice changes the `web` gunicorn worker class (sync workers can't serve WebSockets); naive video-in-Mongo hits the 16 MB BSON limit. **Resolved 2026-08-28:** shipped as **SSE** (`GET /events` — feeds/chat/notifications) + a web-mounted media volume; Forum real-time + media are built and live. | Write **one ADR now**: **SSE** (zero-dep, covers feeds + notifications) vs **Flask-SocketIO** (DM → new dep + `gevent`/`eventlet` workers). Pick **GridFS or a volume** for blobs. This maps cleanly onto the roadmap's 3a/3b (no new transport) vs 3c (WebSocket) cut line. |
| 2 | ✅ | AI / scope | `PROPOSAL §5` (v1) named **5** classes incl. **"Injury Risk"**; PMData has **no injury label** and ~3 natural classes (`ai/README.md:24-26`). **Resolved 2026-07-20:** the TA's [`GUIDELINES.md`](GUIDELINES.md) (`WSNH_Guidelines.pdf`) is the source of truth and permits notified feature changes; the team's v2 proposal generalized the class set, and the shipped **3-class RF (Rest/Moderate/Ready)** satisfies it — **no 5th class owed, nothing pending.** | *(historical)* Lowest-risk option had been to keep "Injury Risk" as a rule-based label; not needed under the v2 spec. |
| 3 | ✅ | Scaling | "**multiprocessing** for inference" is the stated scaling story (`DESIGN.md:41`), but a single Random-Forest `.predict()` is sub-millisecond — a per-request process pool costs *more* than it saves; the TA's "measure, don't guess" (L8) would flag it. **Resolved:** REPORT §4 + `DESIGN.md:112` state the measured horizontal story; the pool is the +5-mandated `/predict` queue. | Make the **headline** story **gunicorn `--workers` + `ai` replicas** (`docker compose up --scale ai=N`; `web`→`ai` service-DNS round-robins — already wired via `AI_URL=http://ai:5000`). Prove it with the locust stress test. Keep multiprocessing only for genuinely CPU-heavy, **measured** work (batch scoring, training, an L6 hot loop). |
| 4 | ✅ | Auth × scale | `DESIGN.md:29` says "session/token" undifferentiated. In-memory Flask sessions break when `web` scales to N replicas (rubric: "scale easily"); the same multi-replica problem hits a Forum WebSocket/SSE layer. | Pick **stateless auth** (signed token, or a DB/Redis-backed session) so `web` scales horizontally — like the big-HW PictureServer's Bearer tokens. **Resolved 2026-08-27:** shipped as a **DB-backed session** — a signed cookie + a random id validated against `active_sids` in the shared Mongo — so it is revocable AND horizontally scalable ([#637](https://github.com/LiorBenSidi/work-smarter-not-harder/issues/637)). |
| 5 | ✅ | Contract drift | `recommendations` is an **object** in the doc (`DESIGN.md:33`) but a **list** `[]` in the code (`ai/app.py:33`). The contract test only checks the *key name*, so the drift passed CI. **Resolved:** `DESIGN.md:52` states `recommendations` is a **list**, matching `ai/app.py`. | Pin **one** shape in `DESIGN §3` + the placeholder. (AI owner's call — it's Shiri's contract.) |
| 6 | ✅ | Test quality | `test_ai_predict_returns_the_contract_keys` greps `ai/app.py` **source** for `state=` etc. — that's *mechanism, not behaviour* (the anti-pattern the repo's own `CLAUDE.md` forbids). A valid `jsonify({"state":…})` would fail it. **Resolved:** source-grep test removed; `/predict` keys asserted behaviourally (`test_ai_queue_contract.py:106`). | Rewrite as a **behavioural** test: `create_app().test_client().post("/predict", json=…)` → assert the JSON has the keys. Stronger and non-brittle. |
| 7 | 🟢 | Deploy (+10) | CI gate + the **deploy job now exist** in `ci.yml` (GHCR build/push → SSH-deploy-to-Azure → Caddy HTTPS + auto-rollback), gated on `vars.SSH_HOST != '' && vars.DEPLOY_ENABLED == 'true'`; the deploy is **live** (since 8 Jul, Elad) and the stress tests are wired. | Built (was "next phase"). The only-`web`-exposed + env-config architecture supported the clean deploy job on green `main`, as designed. |
| 8 | 🟡 | `/predict` errors | No error/timeout/version semantics; `ai_client` treats any non-2xx as "down → `None`", so a malformed-feature bug looks like an outage (silent-failure smell). | When the model lands, give `/predict` a **400 vs 5xx** distinction so bad input ≠ AI-down. Low priority. |

## Rubric coverage — does the architecture reach 100?
| Item | Pts | Supported? | Gap |
|---|---|---|---|
| Whole app F1–F9 on Docker | 75 | **Yes** — containers, contracts, data model map to every feature | Finding 2 (Injury-Risk) + the F6+F7 merge — **resolved** (settled by the TA's guidelines + the v2 spec; not pending) |
| Online Forum (real-time, 8 sub-features) | 10 | **✅ built** | Finding 1 resolved — shipped as SSE + a web-mounted media volume (see the Findings table) |
| Azure deploy + CI/CD auto-deploy | 10 | **✅ live** (CI + deploy job + auto-rollback; VM live since 8 Jul) | Finding 4 (auth statefulness) resolved: DB-backed session revocation shipped |

## Decisions that were needed pre-build — all since settled
*(Resolved during the build; kept for the pre-build record: 1 — Injury-Risk dropped per the v2 spec; 2 — shipped SSE; 3 — a web-mounted media volume; 4 — DB-backed session ✅; 5 — `recommendations` is a list.)*
1. **Noam email** — keep "Injury Risk" rule-based (no permission needed) **or** bundle "5 → ~3 classes / drop Injury-Risk" into the F6+F7 email. *(team → Noam)*
2. **Forum real-time transport** — SSE vs Flask-SocketIO (changes the `web` worker class). *(team)*
3. **Forum media storage** — GridFS vs volume vs object store (16 MB BSON limit). *(Elad)*
4. **Auth statefulness** — ✅ **resolved**: shipped a DB-backed session (signed cookie + `active_sids` in shared Mongo) — revocable and scalable ([#637](https://github.com/LiorBenSidi/work-smarter-not-harder/issues/637)). *(Lior)*
5. **`recommendations` shape** — object vs array; pin the `/predict` seam. *(Shiri)*

## Cheap fixes worth doing before building (non-architectural)
- Findings **5** (pin `recommendations` shape) and **6** (behavioural contract test) are small and high-value — can ship as a follow-up PR.
- `ai/app.py`'s docstring says it "returns a 501 placeholder" but the code returns **200** with the contract shape (the 200 is *correct* — it lets `web` integrate before the model lands; keep the code, fix the comment). Day-1 comment-rot per L8.1.

---
*Advisory only — changes no contract. Produced by the pre-build architecture-validation pass (engineering-plugin lenses) requested before the Saturday kickoff. Supersedes nothing; `DESIGN.md` remains the living design.*
