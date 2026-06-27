# Architecture Review — Work Smarter, Not Harder

**Type:** design validation (pre-build) · **Date:** 2026-06-27 · **Status:** advisory — changes **no** contract.
**Lenses:** system-design · architecture (ADR) · code-review · testing-strategy.
**Validated against:** [`PROPOSAL.md`](PROPOSAL.md) (graded 100/100 — the contract) · [`PROPOSAL-v2.md`](PROPOSAL-v2.md) (intent) ·
Noam's rubric [`FEEDBACK.md`](FEEDBACK.md) (80 + 10 + 10) · the WSML course rules · the live skeleton (`docker-compose.yml`, `web/`, `ai/`, `tests/`).

**Resolution (2026-06-27):** findings **3, 4, 5, 6** are fixed in the follow-up PR — scaling story corrected to replicas + workers; auth-scale note added; the `/predict` shape pinned (`recommendations` is a list, key is `state`); the contract test made behavioural. **1, 2** remain open *decisions* (Forum transport/storage ADR; Injury-Risk pending the Noam email). **7, 8** are later phases (deploy job; `/predict` 400-vs-5xx when the model lands).

## Verdict
The 3-container design is **sound for the 80-point app and the CI half of the deploy +10** — the seams are real,
enforced by tests, and AirPlay-safe. **The team can start building.** But two architecture decisions are still
unfaced and they *ripple into the `web` container's runtime*, so decide them **before** the code they touch lands —
not at Phase 3: **(1) the Forum's real-time + media-storage layer**, and **(2) stateless auth for horizontal scale**.
Separately, one proposal-scope item — **cutting the 5 readiness classes to ~3 / dropping "Injury Risk"** — is the
*same kind of change* as the F6+F7 merge and needs the *same Noam sign-off* (or a zero-cost workaround). Details below.

## What's sound (keep it)
- **Container split & exposure** — only `web` publishes a host port (`8000:5000`); `ai`+`db` are `expose`-only, and
  `Integration_Tests/test_skeleton_contract.py` enforces it. Meets "≥3 communicating containers, only `web` exposed"
  and dodges the macOS-AirPlay-on-5000 trap. (`docker-compose.yml:5-44`)
- **Startup ordering** — healthchecks on all 3 + `depends_on: service_healthy`; `web` won't serve before `ai`/`db`
  are ready. (`docker-compose.yml:15-44`)
- **Production server** — `gunicorn` in both app containers (not the Flask dev server). (`web/Dockerfile:11`, `ai/Dockerfile:14`)
- **Model-bake discipline** — `ai/Dockerfile` documents joblib-bake + pin-sklearn (the Mini-HW2 lesson); no runtime
  train/download. (`ai/Dockerfile:8-14`, `ai/requirements.txt:4-6`)
- **Fault tolerance is wired, not just promised** — `ai_client.predict()` catches `RequestException` → logs → returns
  `None`, so the caller degrades and the app can't crash on an AI outage. (`web/services/ai_client.py:19-21`)
- **No hardcoded secrets** — env-driven config; compose makes `SECRET_KEY` mandatory (`${SECRET_KEY:?…}`). (`web/config.py`, `docker-compose.yml:10`)
- **Security deps present up front** — `werkzeug` (hashing) + `flask-limiter` (rate-limit) + `pymongo`. (`web/requirements.txt`)
- **Contract-based ownership** — fixed seams + implementation freedom; matches L5.1 interfaces + L8.1 "don't polish
  teammates' code". (`docs/DESIGN.md:7-8`)
- **The test gate is load-bearing** — 5 type-dirs; real contract tests enforce the seams now; CI **fails on 0 collected
  tests** (no false-green). (`tests/README.md`, `.github/workflows/ci.yml:37`)

## Findings

| # | Sev | Area | Issue | Fix — before the code it touches |
|---|---|---|---|---|
| 1 | 🔴 | Forum (+10) | The architecture covers only the 80-pt app. The Forum's **mandatory real-time** feeds/chat/notifications (`FEEDBACK.md:61`) and **image/video** storage have **no home** — deferred to "Phase 3" (`DESIGN.md:63`). Transport choice changes the `web` gunicorn worker class (sync workers can't serve WebSockets); naive video-in-Mongo hits the 16 MB BSON limit. | Write **one ADR now**: **SSE** (zero-dep, covers feeds + notifications) vs **Flask-SocketIO** (DM → new dep + `gevent`/`eventlet` workers). Pick **GridFS or a volume** for blobs. This maps cleanly onto the roadmap's 3a/3b (no new transport) vs 3c (WebSocket) cut line. |
| 2 | 🔴 | AI / scope | `PROPOSAL §5` (the **graded** contract) names **5** classes incl. **"Injury Risk"**; PMData has **no injury label** and ~3 natural classes (`ai/README.md:24-26`). Shipping 3 + dropping a named class = "removing something from the proposal" → needs Noam's OK (`FEEDBACK.md:46`), exactly like F6+F7. | Lowest-risk: **keep "Injury Risk" as a rule-based label** (threshold, not ML) → all 5 delivered, **no permission needed**. Otherwise fold "5 → ~3 / drop Injury-Risk" into the **same Noam email** as F6+F7. |
| 3 | 🟠 | Scaling | "**multiprocessing** for inference" is the stated scaling story (`DESIGN.md:41`), but a single Random-Forest `.predict()` is sub-millisecond — a per-request process pool costs *more* than it saves; the TA's "measure, don't guess" (L8) would flag it. | Make the **headline** story **gunicorn `--workers` + `ai` replicas** (`docker compose up --scale ai=N`; `web`→`ai` service-DNS round-robins — already wired via `AI_URL=http://ai:5000`). Prove it with the locust stress test. Keep multiprocessing only for genuinely CPU-heavy, **measured** work (batch scoring, training, an L6 hot loop). |
| 4 | 🟠 | Auth × scale | `DESIGN.md:29` says "session/token" undifferentiated. In-memory Flask sessions break when `web` scales to N replicas (rubric: "scale easily"); the same multi-replica problem hits a Forum WebSocket/SSE layer. | Pick **stateless auth** (signed token, or a DB/Redis-backed session) so `web` scales horizontally — like the big-HW PictureServer's Bearer tokens. Decide now; cheap at the seam, expensive to retrofit. |
| 5 | 🟠 | Contract drift | `recommendations` is an **object** in the doc (`DESIGN.md:33`) but a **list** `[]` in the code (`ai/app.py:33`). The contract test only checks the *key name*, so the drift passed CI. | Pin **one** shape in `DESIGN §3` + the placeholder. (AI owner's call — it's Lior's contract.) |
| 6 | 🟠 | Test quality | `test_ai_predict_returns_the_contract_keys` greps `ai/app.py` **source** for `state=` etc. — that's *mechanism, not behaviour* (the anti-pattern the repo's own `CLAUDE.md` forbids). A valid `jsonify({"state":…})` would fail it. | Rewrite as a **behavioural** test: `create_app().test_client().post("/predict", json=…)` → assert the JSON has the keys. Stronger and non-brittle. |
| 7 | 🟡 | Deploy (+10) | CI gate exists (the 5-pt CI-only partial — correctly claimed, `ROADMAP.md:36`); **no deploy job** + no Azure yet; stress tests aren't wired (they need a running stack). | Expected — it's the next phase. The architecture (only-`web`-exposed + env config) already supports a clean deploy job on green `main`. |
| 8 | 🟡 | `/predict` errors | No error/timeout/version semantics; `ai_client` treats any non-2xx as "down → `None`", so a malformed-feature bug looks like an outage (silent-failure smell). | When the model lands, give `/predict` a **400 vs 5xx** distinction so bad input ≠ AI-down. Low priority. |

## Rubric coverage — does the architecture reach 100?
| Item | Pts | Supported? | Gap |
|---|---|---|---|
| Whole app F1–F9 on Docker | 80 | **Yes** — containers, contracts, data model map to every feature | Finding 2 (Injury-Risk) + the F6+F7 merge need Noam's OK |
| Online Forum (real-time, 8 sub-features) | 10 | **Not yet** | Finding 1 — decide transport + blob storage before Phase 3 |
| Azure deploy + CI/CD auto-deploy | 10 | **Half** (CI = 5) | Finding 7 (deploy job) + Finding 4 (stateless auth for "scale easily") |

## Decisions needing a team / Noam call
1. **Noam email** — keep "Injury Risk" rule-based (no permission needed) **or** bundle "5 → ~3 classes / drop Injury-Risk" into the F6+F7 email. *(team → Noam)*
2. **Forum real-time transport** — SSE vs Flask-SocketIO (changes the `web` worker class). *(team)*
3. **Forum media storage** — GridFS vs volume vs object store (16 MB BSON limit). *(Elad)*
4. **Auth statefulness** — stateless token vs server session, given `web` scales. *(Shiri; architecture-level)*
5. **`recommendations` shape** — object vs array; pin the `/predict` seam. *(Lior)*

## Cheap fixes worth doing before building (non-architectural)
- Findings **5** (pin `recommendations` shape) and **6** (behavioural contract test) are small and high-value — can ship as a follow-up PR.
- `ai/app.py`'s docstring says it "returns a 501 placeholder" but the code returns **200** with the contract shape (the 200 is *correct* — it lets `web` integrate before the model lands; keep the code, fix the comment). Day-1 comment-rot per L8.1.

---
*Advisory only — changes no contract. Produced by the pre-build architecture-validation pass (engineering-plugin lenses) requested before the Saturday kickoff. Supersedes nothing; `DESIGN.md` remains the living design.*
