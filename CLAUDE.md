# CLAUDE.md — Work Smarter, Not Harder

Guidance for AI agents (and humans) working in this repo. **Claude Code loads this file automatically every session**, so the conventions here are picked up without anyone having to open `CONTRIBUTING.md`.

## Project
**Work Smarter, Not Harder** — an AI-powered sports-coaching platform. WSML final project (Technion 00950219),
team "Git Push & Pray" (Lior · Shiri · Elad). Full spec: [`docs/PROPOSAL.md`](docs/PROPOSAL.md); official
requirements: [`docs/Proj_Guidelines.pdf`](docs/Proj_Guidelines.pdf) + [`docs/TA-Notes.txt`](docs/TA-Notes.txt).

## Current status (updated 2026-07-02) — read this first
The backend is built and CI-gated; the open work is two teammates' lanes. If you're picking up work, build
**within** an open lane below, keep `main` green (PR-only), and **don't re-do or "polish" the built parts**.
- ✅ **Built (Lior):** the `web` tier (auth · profile · daily check-in · dashboard · history · forum CRUD+UI ·
  **direct messages + live DM notifications** (the Chat tab: conversations · threads · generative avatars · a
  polling notification pulse · an anti-spam messaging rate-limit) · **vote notifications** (an up/downvote pings
  the post author, shown in an Activity feed) · **comment up/down-votes** · SPA frontend + CSRF + installable PWA);
  the **whole data layer** (`web/services/db.py` CRUD + Mongo indexes /
  `$jsonSchema` validators / auth config / `db/seed.py` / backup script); **Week-9 logging**; the 3-container
  Docker build with fault tolerance; the **CI gate** (ruff · bandit · pytest); and the **CI/CD deploy pipeline**
  (GHCR build/push → SSH-deploy to the Azure VM → Caddy HTTPS, `docker-compose.prod.yml`, auto-rollback, `/ready`
  gate). Full test suite green on `main`. Deploy detail: [`docs/CICD_REPORT.md`](docs/CICD_REPORT.md) · demo run-sheet:
  [`docs/DEPLOY_DEMO.md`](docs/DEPLOY_DEMO.md).
- ⏳ **Open — Shiri (`ai/`):** the real Random Forest model + recommendation engine behind `POST /predict` — it's a
  contract-shaped **placeholder** today. See [`PERSON1.md`](PERSON1.md).
- ⏳ **Open — Elad:** the **live** Azure deploy (VM provisioning + the demo — the pipeline *code* is done);
  scaling (`ai` replicas / gunicorn workers + a locust before/after) and the risk-assessment section.
  *Done:* Forum/DM media + `flask-limiter` on the public routes (#160); the **cross-container test-runner**
  (`docker-compose.test.yml` + `tests/Dockerfile`, CI job `compose-e2e` gating `build`→`deploy`), the
  **fault-isolation** + **locust stress** suites, and the deploy-contract guard tests. See [`PERSON3.md`](PERSON3.md).
- ℹ️ **Online Forum (§10) status:** posts · comments · anonymity · post up/down-votes · **P2P direct messages
  (text) · live DM notifications (SSE push) · anti-spam messaging rate-limit** are built. Still open: media
  attachments + file-size limits · a received-engagement profile metric ·
  fuller cold-seeding (the seed content is Shiri's). See [`docs/FEEDBACK.md`](docs/FEEDBACK.md) §2 for the rubric.

## ⛔ Workflow — `main` is PR-only (enforced server-side)
- **Never push to `main`.** It's branch-protected — direct pushes are rejected for everyone, including admins.
- Every change: **branch → commit → push → open a PR → CI green → self-merge.** No peer approval required — own your scope + tests; CI is the gate.
- Branch names: `feat/…` · `fix/…` · `test/…` · `docs/…` · `chore/…`.
- **Never use `git ... --force` (no `push --force`, no force-merge)** — especially when a PR shows conflicts or the merge won't go through. A force-push can silently overwrite a teammate's work. Instead: open the PR on GitHub, review **each conflict individually**, and **tell the teammate you conflict with** before resolving — so nobody overwrites anyone else's changes without both sides agreeing. (Team rule from Lior.)
- Full flow + commands: [`CONTRIBUTING.md`](CONTRIBUTING.md).
- **Local gate before you commit** (same checks as CI): `git commit` runs ruff (incl. the no-`print()` rule) + bandit; `git push` runs pytest. Enable once: `sh scripts/setup-hooks.sh` + `pip install -r requirements-dev.txt`.

## Architecture (3 containers — only `web` is exposed)
- **`web/`** — Flask: auth (password hashing via `werkzeug.security`), API endpoints, frontend. The ONLY user-facing container.
- **`db`** — MongoDB: users, profiles, programs, analysis_history. Internal only.
- **`ai/`** — Random Forest readiness classifier + recommendation engine. Internal REST (`POST /predict`).

## Auth modes & the debug panel (two dev switches)
Full guide: [`docs/AUTH_TESTING.md`](docs/AUTH_TESTING.md); secrets + live-email setup (local · server · CI/CD): [`SECRETS.md`](SECRETS.md). Both default **off** (mock email, desktop viewport); neither affects normal users.
- **Email mock ⇄ live = `SMTP_HOST`.** Unset (default) → login-OTP / signup-verify / password-reset codes are shown on screen + logged (no mailbox — what teammates + grading use); set `SMTP_*` + `MAIL_FROM` in `.env` → codes are emailed only. `docker compose up` reads `.env` and passes **every** auth-mode var (`OTP_ENABLED`, `REGISTER_VERIFY_EMAIL`, `OTP_TTL_SECONDS`, …) through to `web`, so flip any mode in `.env` alone; `curl localhost:8000/auth/config` reports `email_mode`.
- **Viewport desktop ⇄ mobile = the `?debug=1` panel.** Append `?debug=1` → a ⚙ **Debug tools** panel (bottom-right) previews the real mobile layout in an iframe inside a desktop browser. Dev-only, gated on `?debug=1` / `localStorage ws-debug`, never shown to normal users.

## Build constraints (from the course rubric — keep these true)
- **Only `web` is published**; `db`/`ai` stay internal (no host ports).
- **Local AI model**, never an external API. **Bake the trained model into the image** (`joblib.dump` → `COPY` → `joblib.load`); never train or download it at container runtime. Pin the `scikit-learn` version so the pickle loads.
- **Security:** hash passwords (werkzeug), auth-gate protected endpoints, rate-limit, validate input, defend against NoSQL injection.
- **Tests:** all 5 types live under `tests/` — `Unit_Tests`, `Integration_Tests`, `System_Tests`, `Stress_Tests`, `Security_Tests`. Add tests alongside the code.
- **Fault tolerance:** handle AI / DB / wearable-API failures gracefully (try/except + sensible fallbacks).
- **Parallel/scaling:** horizontal — gunicorn `--workers` + `ai` replicas (`--scale ai=N`); reserve `multiprocessing` for *measured* CPU-heavy work (batch scoring, training, an L6 hot loop), not a sub-ms per-request RF predict (L8: "measure, don't guess").
- **Performance / native code (course L6, native-vs-Python):** Python is PVM-interpreted and slow for tight loops, so for a **measured** hot path — e.g. numeric loops in the `ai` feature/inference pipeline — don't hand-roll pure-Python loops. First **vectorize with NumPy**; where that's still the bottleneck, drop to a **compiled extension (Cython / a C extension / `cffi`)**. Always **measure first** (L8: "don't guess, profile"), optimize only the proven hot spot, keep a pure-Python fallback, and **build any native module into the image** (never compile at container runtime).
- **No `print()` in committed code** — use `logging` (course L3: print is slow; L8.1: raise errors, not print). Enforced by ruff `T20` in CI **and** the local hooks; a deliberate one-off needs `# noqa: T201`.
- **Secrets:** never commit `.env` (commit `.env.example`). No real student IDs in committed filenames.

## Testing & TDD (course-graded — this is how we test)
- **TDD-first.** Write the test before/with the code (Red → Green → Refactor). The built areas (web + data) already carry full tests; for new code, add its tests alongside it (see [`tests/README.md`](tests/README.md) — the feature×test matrix). The suite's skipped tests are **env-gated** (real Mongo via `TEST_MONGO_URI`, a live stack via `E2E_BASE_URL`) — not unwritten scaffolds; CI runs them with a `mongo:7` service.
- **All 5 test types** live in `tests/{Unit,Integration,System,Stress,Security}_Tests/`. CI runs the whole suite on every PR; the pre-push hook runs it locally.
- **How the web suite runs with no Mongo / no Docker** (read `tests/conftest.py`): it execs `web/app.py` off disk and injects in-memory fakes (`FakeUsers` · `FakeProfiles` · `FakeHistory` · `FakeForum` · `FakeMessages` · `FakeNotifications`) into `create_app(users=…, profiles=…, …)`. The `web→db` seam is just `.get/.add/.save/.list`, so the fakes mirror `web/services/db.py`'s contract — keep them in sync when you change that seam. Use the ready-made fixtures (`client`, `profile_client`, `forum_client`, `messages_client`, `otp_client`, `rate_limited_client`); the `_CsrfClient` wrapper auto-sends the double-submit CSRF token so feature tests don't replumb it.
- **No AI-slop tests** (course L3): test *behaviour*, not the implementation. Never write a test that passes trivially (`assert True`) or just mirrors the code — a test must be able to fail for a real reason.
- **A broken test gets fixed or deleted — never commented out** (L8.1; the TA reads test code).
- **Tests run on any machine** — env vars, no local/absolute paths; honour the `TESTING` flag.
- **Stay in your contract.** Don't change a shared seam (the `/predict` shape, the Mongo collections, only-`web`-exposed) without telling the team; and **don't polish teammates' working code** (L8.1) — implementation behind your own contract is yours.

## Commands
```bash
sh scripts/setup-hooks.sh       # one-time: enable the local pre-commit / pre-push hooks
pip install -r requirements-dev.txt  # one-time: pinned dev tools (ruff, bandit, pytest)
docker compose up --build       # run the full stack (web/db/ai)
python -m pytest tests/         # run the whole suite (what CI + the pre-push hook run)

# Narrower runs (same interpreter, no Docker needed for the web/data tests):
python -m pytest tests/Unit_Tests tests/Security_Tests            # one or more suites
python -m pytest tests/Unit_Tests/test_db.py                      # one file
python -m pytest tests/Unit_Tests/test_db.py::test_add_is_idempotent  # one test
python -m pytest -k forum                                         # by keyword across the suite

# Opt into the env-gated tests that are otherwise skipped (see Testing note below):
TEST_MONGO_URI=mongodb://localhost:27017 python -m pytest tests/Integration_Tests/test_db_mongo.py  # real Mongo
E2E_BASE_URL=http://localhost:8000 python -m pytest tests/System_Tests                               # live stack

# Cross-container harness — boots the 3 containers + the test-runner, exits with the runner's code (CI: `compose-e2e`):
docker compose -f docker-compose.yml -f docker-compose.test.yml up --build --exit-code-from tests

# Destructive fault-isolation (stops ai/db, restarts them) + the stress burst — need a stack already up:
FAULT_TEST=1 E2E_BASE_URL=http://localhost:8000 python -m pytest tests/System_Tests/test_fault_isolation.py
E2E_BASE_URL=http://localhost:8000 python -m pytest tests/Stress_Tests   # locust: see tests/Stress_Tests/locustfile.py
```

## Where things are
- `docs/` — proposal, official guidelines, TA notes, design doc, meeting notes.
- `CONTRIBUTING.md` — the PR workflow.
- `web/` — the built web app + data layer · `ai/` — the AI container (Shiri's model is still a placeholder) · `tests/` — the 5 test suites (web/data covered; AI + stress/integration still to grow).
