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
| Auth (F1) | ✓ | ✓ | ✓ | – | ✓ | Lior | `Security_Tests/test_auth.py` |
| Profile (F2) | ✓ | ✓ | ✓ | – | ✓ inj. | Lior | (add) |
| Readiness (F3) | ✓ | ✓ | ✓ | ✓ | – | Shiri | `Unit_Tests/test_ai.py`, `Integration_Tests/test_web_ai.py` |
| Calorie (F4) | ✓ | ✓ | ✓ | – | – | Shiri | `Unit_Tests/test_calories.py` (unit ✓) |
| Workout (F5) | ✓ | ✓ | ✓ | – | – | Shiri | (add) |
| Dashboard / History (F7/F8) | ✓ | ✓ | ✓ | – | – | Lior | `System_Tests/test_e2e.py` |
| Deploy + CI/CD | – | ✓ | ✓ | ✓ | – | Lior (CI) / Elad (deploy + stress) | `Integration_Tests/test_deploy_contract.py`, `Stress_Tests/test_load.py` |
| Forum media (§10) | – | ✓ | – | – | ✓ | Elad | `Integration_Tests/test_media.py`, `Security_Tests/test_media_limits.py` |

(✓ = required; – = N/A for that feature. Refine against the proposal's own feature×test matrix as you build.)

## The cross-container test-runner (OWNER: Elad)
The suites above run **in-process** (Flask test client + injected fakes — no Docker). That cannot prove the
real wire path, so a 4th container runs the same code **against the live stack**:

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml up --build --exit-code-from tests
```

It builds `tests/Dockerfile`, waits for `web` + `db` to report healthy, then runs `System_Tests` (over HTTP,
`E2E_BASE_URL=http://web:5000`) and the real-Mongo data-layer suite (`TEST_MONGO_URI` → the throwaway
`worksmarter_test` DB). The job's exit code **is** the runner's. CI runs this on every PR (`compose-e2e`), and
`build` → `deploy` depend on it, so a broken container path can never reach GHCR or the VM.

## Env-gated suites (they skip, they are not unwritten)
| Suite | Un-skip with | What it proves |
|---|---|---|
| `Integration_Tests/test_db_mongo.py` | `TEST_MONGO_URI` | the data layer against a real MongoDB |
| `System_Tests/test_e2e.py` | `E2E_BASE_URL` | register → profile → check-in → dashboard over real HTTP |
| `System_Tests/test_fault_isolation.py` | `FAULT_TEST=1` + `E2E_BASE_URL` | **destructive**: stops `ai`/`db` — web survives, `/ready` degrades to 503 |
| `Stress_Tests/test_load.py` | `E2E_BASE_URL` | a concurrency burst sheds load with 429, never 5xx |
| `Stress_Tests/locustfile.py` | run `locust` (CI: *Run workflow*) | ramped load; 429 = the rate-limit defending, 5xx = a real failure |
