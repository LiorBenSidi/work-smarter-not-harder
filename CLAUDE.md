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
  polling notification pulse · an anti-spam messaging rate-limit) · SPA frontend + CSRF + installable PWA);
  the **whole data layer** (`web/services/db.py` CRUD + Mongo indexes /
  `$jsonSchema` validators / auth config / `db/seed.py` / backup script); **Week-9 logging**; the 3-container
  Docker build with fault tolerance; the **CI gate** (ruff · bandit · pytest); and the **CI/CD deploy pipeline**
  (GHCR build/push → SSH-deploy to the Azure VM → Caddy HTTPS, `docker-compose.prod.yml`, auto-rollback, `/ready`
  gate). 332 tests, `main` green. Deploy detail: [`docs/CICD_REPORT.md`](docs/CICD_REPORT.md) · demo run-sheet:
  [`docs/DEPLOY_DEMO.md`](docs/DEPLOY_DEMO.md).
- ⏳ **Open — Shiri (`ai/`):** the real Random Forest model + recommendation engine behind `POST /predict` — it's a
  contract-shaped **placeholder** today. See [`PERSON1.md`](PERSON1.md).
- ⏳ **Open — Elad:** the **live** Azure deploy (VM provisioning + the demo — the pipeline *code* is done); the
  remaining Forum media/attachments (images/video in posts, comments and DMs + file-size limits) and
  upvote/downvote notifications; `flask-limiter` on the other public routes; stress tests (locust); the
  test-runner service. See [`PERSON3.md`](PERSON3.md).
- ℹ️ **Online Forum (§10) status:** posts · comments · anonymity · post up/down-votes · **P2P direct messages
  (text) · live DM notifications (SSE push) · anti-spam messaging rate-limit** are built. Still open: media
  attachments + file-size limits · vote notifications · comment votes · a received-engagement profile metric ·
  fuller cold-seeding (the seed content is Shiri's). See [`docs/FEEDBACK.md`](docs/FEEDBACK.md) §2 for the rubric.

## ⛔ Workflow — `main` is PR-only (enforced server-side)
- **Never push to `main`.** It's branch-protected — direct pushes are rejected for everyone, including admins.
- Every change: **branch → commit → push → open a PR → CI green → self-merge.** No peer approval required — own your scope + tests; CI is the gate.
- Branch names: `feat/…` · `fix/…` · `test/…` · `docs/…` · `chore/…`.
- Full flow + commands: [`CONTRIBUTING.md`](CONTRIBUTING.md).
- **Local gate before you commit** (same checks as CI): `git commit` runs ruff (incl. the no-`print()` rule) + bandit; `git push` runs pytest. Enable once: `sh scripts/setup-hooks.sh` + `pip install -r requirements-dev.txt`.

## Architecture (3 containers — only `web` is exposed)
- **`web/`** — Flask: auth (password hashing via `werkzeug.security`), API endpoints, frontend. The ONLY user-facing container.
- **`db`** — MongoDB: users, profiles, programs, analysis_history. Internal only.
- **`ai/`** — Random Forest readiness classifier + recommendation engine. Internal REST (`POST /predict`).

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
- **No AI-slop tests** (course L3): test *behaviour*, not the implementation. Never write a test that passes trivially (`assert True`) or just mirrors the code — a test must be able to fail for a real reason.
- **A broken test gets fixed or deleted — never commented out** (L8.1; the TA reads test code).
- **Tests run on any machine** — env vars, no local/absolute paths; honour the `TESTING` flag.
- **Stay in your contract.** Don't change a shared seam (the `/predict` shape, the Mongo collections, only-`web`-exposed) without telling the team; and **don't polish teammates' working code** (L8.1) — implementation behind your own contract is yours.

## Commands
```bash
sh scripts/setup-hooks.sh       # one-time: enable the local pre-commit / pre-push hooks
pip install -r requirements-dev.txt  # one-time: pinned dev tools (ruff, bandit, pytest)
docker compose up --build       # run the full stack (web/db/ai)
python -m pytest tests/         # run the test suite
```

## Where things are
- `docs/` — proposal, official guidelines, TA notes, design doc, meeting notes.
- `CONTRIBUTING.md` — the PR workflow.
- `web/` — the built web app + data layer · `ai/` — the AI container (Shiri's model is still a placeholder) · `tests/` — the 5 test suites (web/data covered; AI + stress/integration still to grow).
