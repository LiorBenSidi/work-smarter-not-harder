# CLAUDE.md — Work Smarter, Not Harder

Guidance for AI agents (and humans) working in this repo. **Claude Code loads this file automatically every session**, so the conventions here are picked up without anyone having to open `CONTRIBUTING.md`.

## Project
**Work Smarter, Not Harder** — an AI-powered sports-coaching platform. WSML final project (Technion 00950219),
team "Git Push & Pray" (Lior · Shiri · Elad). Full spec: [`docs/PROPOSAL.md`](docs/PROPOSAL.md); official
requirements: [`docs/Proj_Guidelines.pdf`](docs/Proj_Guidelines.pdf) + [`docs/TA-Notes.txt`](docs/TA-Notes.txt).

## ⛔ Workflow — `main` is PR-only (enforced server-side)
- **Never push to `main`.** It's branch-protected — direct pushes are rejected for everyone, including admins.
- Every change: **branch → commit → push → open a PR → a teammate approves → merge.**
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
- **Parallel/scaling:** CPU-bound inference → `multiprocessing`; `ai` replicas for the multi-machine story.
- **Performance / native code (course L6, native-vs-Python):** Python is PVM-interpreted and slow for tight loops, so for a **measured** hot path — e.g. numeric loops in the `ai` feature/inference pipeline — don't hand-roll pure-Python loops. First **vectorize with NumPy**; where that's still the bottleneck, drop to a **compiled extension (Cython / a C extension / `cffi`)**. Always **measure first** (L8: "don't guess, profile"), optimize only the proven hot spot, keep a pure-Python fallback, and **build any native module into the image** (never compile at container runtime).
- **No `print()` in committed code** — use `logging` (course L3: print is slow; L8.1: raise errors, not print). Enforced by ruff `T20` in CI **and** the local hooks; a deliberate one-off needs `# noqa: T201`.
- **Secrets:** never commit `.env` (commit `.env.example`). No real student IDs in committed filenames.

## Commands (fill in as the stack lands)
```bash
sh scripts/setup-hooks.sh       # one-time: enable the local pre-commit / pre-push hooks
pip install -r requirements-dev.txt  # one-time: pinned dev tools (ruff, bandit, pytest)
docker compose up --build       # run the full stack (web/db/ai)
python -m pytest tests/         # run the test suite
```

## Where things are
- `docs/` — proposal, official guidelines, TA notes, design doc, meeting notes.
- `CONTRIBUTING.md` — the PR workflow.
- `web/`, `ai/`, `tests/` — the app (to build).
