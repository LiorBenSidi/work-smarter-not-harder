# Work Smarter, Not Harder

An **AI-powered sports-coaching platform** — WSML final project (Technion 00950219).
Athletes enter profile + recovery metrics; a **local Random Forest classifier** predicts training-readiness
(Ready / Moderate / Recovery-Needed / Deload / Injury-Risk); a recommendation engine turns that into action
plans, workouts, program-balance analysis, and calorie targets.

**Team (Git Push & Pray):** Lior Ben Sidi · Shiri Haboob · Elad Nachalieli
**Full spec:** [`docs/PROPOSAL.md`](docs/PROPOSAL.md) (the submitted proposal).

## Architecture (3 containers — only `web` is exposed)
| Container | Role |
|---|---|
| `web/` | Flask frontend + authentication (werkzeug hashing) + API. **The only user-facing container.** |
| `db`   | MongoDB — users, profiles, programs, analysis history. Internal only. |
| `ai/`  | Random Forest inference + recommendation engine. Internal REST (`POST /predict`). |

Course rules this satisfies: ≥3 communicating containers, only `web` exposed, local AI model (no external API),
all 5 test types, fault tolerance, parallel scaling, password hashing + injection defense.

## Repo layout
```
web/     Flask web container (to build)
ai/      Random Forest + recommendation engine (to build)
tests/   Unit_Tests · Integration_Tests · System_Tests · Stress_Tests · Security_Tests
docs/    PROPOSAL.md (the submitted spec)
```
This is a starting scaffold — the team fills it in via pull requests (see below).

## Getting started (first-time, every clone)
After cloning, enable the local quality gate so the course's checks run **before** you commit (it mirrors CI):
```sh
sh scripts/setup-hooks.sh                 # enable the shared git hooks (.githooks/)
pip install -r requirements-dev.txt        # in your venv: pinned ruff + bandit + pytest
```
`git commit` then runs ruff (incl. **no `print()`** — use `logging`) + bandit; `git push` runs the tests. Full detail: [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Workflow — PRs only
`main` is protected: **no direct pushes.** All changes land via a pull request from a branch. See
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## For AI agents (any tool)
The workflow is **enforced for every tool and human**: `main` is branch-protected, so direct pushes are
rejected and changes land only via a PR that passes CI — no agent can bypass it, whatever it reads. For
*awareness*, each tool reads its own file; all point to [`CLAUDE.md`](CLAUDE.md) + [`CONTRIBUTING.md`](CONTRIBUTING.md)
as the source of truth:

| Tool | File it reads |
|---|---|
| Claude Code | [`CLAUDE.md`](CLAUDE.md) |
| Codex (+ others via the cross-tool standard) | [`AGENTS.md`](AGENTS.md) |
| GitHub Copilot | [`.github/copilot-instructions.md`](.github/copilot-instructions.md) |
| Cursor | [`.cursor/rules/work-smarter.mdc`](.cursor/rules/work-smarter.mdc) (also reads `AGENTS.md`) |

**Using a tool not listed?** Read `CLAUDE.md` + `CONTRIBUTING.md` — the rules apply regardless, and branch
protection enforces them either way. (We intentionally don't add a separate config file per niche tool — it
clutters the repo and drifts; the README + `AGENTS.md` are the catch-all.)

## Status
Proposal submitted; build in progress. Final project due **23 Aug 2026** (demo Week 12, present 16 July).
