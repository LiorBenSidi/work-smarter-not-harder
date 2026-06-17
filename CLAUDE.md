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
- **Secrets:** never commit `.env` (commit `.env.example`). No real student IDs in committed filenames.

## Commands (fill in as the stack lands)
```bash
docker compose up --build       # run the full stack (web/db/ai)
python -m pytest tests/         # run the test suite
```

## Where things are
- `docs/` — proposal, official guidelines, TA notes, design doc, meeting notes.
- `CONTRIBUTING.md` — the PR workflow.
- `web/`, `ai/`, `tests/` — the app (to build).
