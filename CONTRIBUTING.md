# Contributing

`main` is **protected** — no one (including the owner) pushes to it directly. Every change lands through a
**pull request** from a feature branch, reviewed by a teammate. This keeps `main` always-green and gives the
3-person team a clear integration point.

## Workflow

```bash
# 1. start from an up-to-date main
git checkout main
git pull

# 2. branch (use a clear prefix: feat/ fix/ test/ docs/ chore/)
git checkout -b feat/readiness-classifier

# 3. commit your work
git add -A
git commit -m "ai: train + serve the Random Forest readiness classifier"

# 4. push the BRANCH (never main) and open a PR
git push -u origin feat/readiness-classifier
gh pr create --fill            # or open the PR on github.com

# 5. a teammate reviews + approves, then merge via the PR
```

## Local checks — run before you commit

The repo ships git hooks (`.githooks/`) that run the **same checks as CI**, on your machine,
*before* code leaves it. Enable them once per clone:

```bash
sh scripts/setup-hooks.sh                 # point git at .githooks/ (one-time)
# then, in your ACTIVATED project venv:
pip install -r requirements-dev.txt        # pinned ruff + bandit + pytest
```

| Trigger | Runs | Why here |
|---|---|---|
| `git commit` | **ruff** (lint + **no-`print()`** rule) · **bandit** (security) | fast — catches issues before they're even committed |
| `git push` | **pytest** (`tests/`) | guards what leaves your machine, without slowing every commit |

- **No `print()`** in committed code — use `logging` (course L3: print is slow; L8.1: raise errors, not print). A deliberate one-off needs `# noqa: T201` on that line.
- The hooks are a **safety net, not the authority**: CI re-runs everything and `main` is PR-only. Real emergency bypass — `git commit --no-verify` / `git push --no-verify` — CI still gates the PR.

## Rules
- **Never** `git push origin main` — it's blocked by branch protection; open a PR instead.
- One teammate **approves** each PR before merge (you can't approve your own).
- Keep PRs focused (one feature/fix). Prefer **Squash and merge** for a clean history.
- All members commit regularly (course requirement — contribution is graded).
- Delete the branch after merge.

## Branch naming
`feat/<thing>` · `fix/<thing>` · `test/<thing>` · `docs/<thing>` · `chore/<thing>`
