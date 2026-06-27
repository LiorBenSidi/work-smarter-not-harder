# Copilot instructions — Work Smarter, Not Harder

AI-powered sports-coaching platform (WSML 00950219). Canonical guidance: [`CLAUDE.md`](../CLAUDE.md); PR workflow: [`CONTRIBUTING.md`](../CONTRIBUTING.md).

## Cardinal rule
`main` is branch-protected — **never push to `main`**. Make a branch (`feat|fix|test|docs|chore/…`) and open a PR; CI (ruff · bandit · pytest) must pass, then the **author merges their own PR** — no peer approval required (own your scope + tests; CI is the gate).

## Architecture (3 containers — only `web` is exposed)
- `web/` — Flask: auth (werkzeug hashing) + API + frontend. The only user-facing container.
- `db` — MongoDB (internal).
- `ai/` — Random Forest classifier + recommendation engine; internal `POST /predict`.

## Constraints
Local AI model only (no external API); bake the trained model into the image (no runtime download), pin `scikit-learn`; hash passwords; validate input / guard NoSQL injection; only `web` is published; never commit `.env`; tests live in `tests/{Unit,Integration,System,Stress,Security}_Tests/`.

## Performance & style
- **Never `print()`** in committed code — use `logging` (enforced by ruff `T20`; a one-off needs `# noqa: T201`).
- **Hot paths:** vectorize (NumPy), then a compiled extension (Cython / C / `cffi`) for a *measured* bottleneck — course L6 native-vs-Python; measure first (L8), keep a pure-Python fallback, build it into the image.
- Local hooks mirror CI: `sh scripts/setup-hooks.sh` + `pip install -r requirements-dev.txt` → ruff + bandit on commit, pytest on push.

## Testing & TDD (course)
Write tests **before/with** the code; all 5 types in `tests/` — fill the scaffolds + remove the `skip` (see `tests/README.md`). Test **behaviour, not the implementation** (no `assert True`); a broken test is **fixed or deleted, never commented out**; tests run on any machine. Don't change a shared contract (`/predict`, the DB collections, only-`web`-exposed) without telling the team.
