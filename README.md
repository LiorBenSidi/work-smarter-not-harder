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

## Workflow — PRs only
`main` is protected: **no direct pushes.** All changes land via a pull request from a branch. See
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Status
Proposal submitted; build in progress. Final project due **23 Aug 2026** (demo Week 12, present 16 July).
