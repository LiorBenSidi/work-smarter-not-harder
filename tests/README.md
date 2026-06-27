# tests/ — required tests + how we test

All **5 course test types** live here, one directory each. **CI runs the whole suite on every PR** and the
local **pre-push hook** runs it too — so these are enforced before anything reaches `main`.

## Rules
- **TDD-first.** Write your task's tests (the scaffolds below) *before/with* the implementation, then remove the
  `skip` and fill them. Failing tests block everyone, so scaffolds stay **skipped** until you fill them.
- **Never comment out a broken test** — fix it or delete it (the TA reads test code).
- **Tests must run on any machine** — env vars, no local/absolute paths.
- You **own your tests** — write them your way; the matrix below is the *what*, not the *how*.

## Already enforced (real tests, run on every PR — keep them green)
These are the **universal guardrails** every owner's work must pass before it can merge — wired now, not waiting on anyone:
- `Unit_Tests/test_scaffold.py` — repo structure (containers + the 5 test-type dirs + the proposal) + `.env` never committed.
- `Integration_Tests/test_skeleton_contract.py` — **only `web` exposed**, host-8000-not-5000, all 3 healthchecks,
  the **`/predict` contract shape** (behavioural — boots the ai app, asserts `state`/`proba`/`recommendations` types), gunicorn.
- `Integration_Tests/test_web_smoke.py` — the **web app boots + serves `/health`** (the healthcheck contract). With the
  ai `/predict` test, **both app containers are behaviourally smoke-tested** from day one.

> **Keep the apps bootable for tests** without Docker or the baked model — load heavy resources (the model, Mongo) **lazily**,
> keep `/health` trivial — so these smoke tests run on any machine (course rule).

## Mandatory tests per feature (the matrix — fill the scaffolds)
| Feature | Unit | Integration | System | Stress | Security | Owner | Scaffold |
|---|:-:|:-:|:-:|:-:|:-:|---|---|
| Auth (F1) | ✓ | ✓ | ✓ | – | ✓ | Shiri | `Security_Tests/test_auth.py` |
| Profile (F2) | ✓ | ✓ | ✓ | – | ✓ inj. | Shiri/Elad | (add) |
| Readiness (F3) | ✓ | ✓ | ✓ | ✓ | – | Lior | `Unit_Tests/test_ai.py`, `Integration_Tests/test_web_ai.py` |
| Calorie (F4) | ✓ | ✓ | ✓ | – | – | Lior | (add) |
| Workout (F5) | ✓ | ✓ | ✓ | – | – | Lior | (add) |
| Dashboard / History (F7/F8) | ✓ | ✓ | ✓ | – | – | Shiri | `System_Tests/test_e2e.py` |
| Deploy + CI/CD | – | – | ✓ | ✓ | – | Elad | `Stress_Tests/test_load.py` |

(✓ = required; – = N/A for that feature. Refine against the proposal's own feature×test matrix as you build.)
