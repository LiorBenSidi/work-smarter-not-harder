# AGENTS.md

Instructions for AI coding agents working in this repo (a cross-tool convention; Claude Code also reads `CLAUDE.md`).

Full guidance:
- **[`CLAUDE.md`](CLAUDE.md)** — project overview, architecture, build constraints, commands.
- **[`CONTRIBUTING.md`](CONTRIBUTING.md)** — the pull-request workflow.

## The rule that always applies
**`main` is branch-protected and PR-only — never push directly to `main`.** Work on a branch
(`feat|fix|test|docs|chore/…`) and open a pull request; CI (ruff · bandit · pytest) must pass, then the author
**merges their own PR — no peer approval required** (own your scope + tests; CI is the gate). GitHub enforces the PR + CI rules server-side, so direct pushes are rejected anyway.

## Architecture (3 containers — only `web` is exposed)
- `web/` — Flask: auth (password hashing via `werkzeug.security`) + API + frontend. The only user-facing container.
- `db` — MongoDB (users, profiles, programs, analysis_history). Internal only.
- `ai/` — Random Forest readiness classifier + recommendation engine. Internal REST `POST /predict`.

## Build constraints
Local AI model only (no external API); **bake the trained model into the image** (no runtime download), pin
`scikit-learn`; hash passwords; validate input + guard NoSQL injection; only `web` is published; tests live in
`tests/{Unit,Integration,System,Stress,Security}_Tests/`; never commit `.env` (commit `.env.example`).

## Performance & style (course-taught)
- **No `print()`** in committed code — use `logging` (L3: print is slow; L8.1: raise errors, not print). Enforced by ruff `T20` in CI + the local hooks; a deliberate one-off needs `# noqa: T201`.
- **Hot paths → native code when it pays off (L6, native-vs-Python):** vectorize with NumPy first, then a compiled extension (Cython / a C extension / `cffi`) for a *measured* bottleneck. Measure first (L8), keep a pure-Python fallback, and build the module into the image.
- **Local gate** (mirrors CI): `sh scripts/setup-hooks.sh` + `pip install -r requirements-dev.txt` → ruff + bandit on `git commit`, pytest on `git push`. Use `--no-verify` only in emergencies (CI still gates).
- **Testing & TDD (course):** write tests **before/with** the code; all 5 types live in `tests/` — fill the scaffolds + remove the `skip` (see [`tests/README.md`](tests/README.md)). Test *behaviour*, not the implementation (no `assert True`); a broken test is **fixed or deleted, never commented out**; tests run on any machine. Stay within your contract — don't change a shared seam (`/predict`, the DB collections, only-`web`-exposed) without telling the team.
