# AGENTS.md

Instructions for AI coding agents working in this repo (a cross-tool convention; Claude Code also reads `CLAUDE.md`).

Full guidance:
- **[`CLAUDE.md`](CLAUDE.md)** — project overview, architecture, build constraints, commands.
- **[`CONTRIBUTING.md`](CONTRIBUTING.md)** — the pull-request workflow.

## The rule that always applies
**`main` is branch-protected and PR-only — never push directly to `main`.** Work on a branch
(`feat|fix|test|docs|chore/…`) and open a pull request; CI (ruff · bandit · pytest) must pass and a teammate
must approve before merge. GitHub enforces this server-side, so direct pushes are rejected anyway.

## Architecture (3 containers — only `web` is exposed)
- `web/` — Flask: auth (password hashing via `werkzeug.security`) + API + frontend. The only user-facing container.
- `db` — MongoDB (users, profiles, programs, analysis_history). Internal only.
- `ai/` — Random Forest readiness classifier + recommendation engine. Internal REST `POST /predict`.

## Build constraints
Local AI model only (no external API); **bake the trained model into the image** (no runtime download), pin
`scikit-learn`; hash passwords; validate input + guard NoSQL injection; only `web` is published; tests live in
`tests/{Unit,Integration,System,Stress,Security}_Tests/`; never commit `.env` (commit `.env.example`).
