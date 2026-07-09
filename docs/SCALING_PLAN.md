# PLAN — Scaling + the locust before/after · OWNER: Elad

> Rubric: [`GUIDELINES.md`](GUIDELINES.md) §4 — the deployed site must be *"public and **scalable via
> parallelization**"*. Design contract: [`DESIGN.md`](DESIGN.md) §L7 — *"a locust run before/after
> `--scale ai=2` shows throughput rising."*

## The measurement problem, stated honestly
The model is a placeholder that returns in microseconds. Throughput against it is bounded by HTTP and
Flask, not by scoring — so **scaling it would show no gain, and a before/after table built on it would
be meaningless**. Two workers finishing instantly is not faster than one worker finishing instantly.

So we measure with a **representative CPU-bound workload** in the same seat the real Random Forest will
sit in: `ai/bench.py:cpu_burn`, selected via the existing `AI_WORKER_TARGET` env var that the queue
already resolves by name. Nothing about the request path changes — same queue, same pool, same routes.
Only the function at the bottom differs.

This is the same reason `AI_WORKER_TARGET` exists. `bench.py` ships in the image but is **never the
production target** (`inference:predict_one` is the default, locked by a guard test).

## Two axes, measured separately

| Axis | Knob | What it proves |
|---|---|---|
| **Vertical (in-container)** | `AI_QUEUE_WORKERS=1 → 4` | the process pool overlaps CPU-bound scoring across cores |
| **Horizontal (replicas)** | `docker compose up --scale ai=2` | stateless `ai` containers scale out; `web` round-robins over service DNS |

## The replica caveat (must be documented, not discovered)
`ai`'s job store is **in-memory, per container**. Under `--scale ai=N`:
- `POST /predict` is **replica-safe** — one request, one response, no stored state read back.
- `POST /jobs` + `GET /jobs/<id>` are **not** — the GET round-robins and hits a replica that never saw
  the job, so it 404s ~(N-1)/N of the time.

`web` only ever calls `/predict`, so this is safe today. It is written down here, in the queue's
docstring, and asserted by a guard test so nobody wires `web` to `/jobs` and scales out.

## Deliverables

| File | What |
|---|---|
| `ai/bench.py` | **new** — `cpu_burn(features)`, a deterministic CPU-bound stand-in for the model |
| `docker-compose.scale.yml` | **new** — override: `ai` replicas + `web` gunicorn workers |
| `scripts/scaling_benchmark.py` | **new** — drives `/predict` at fixed concurrency, reports throughput + p95 |
| `docs/SCALING_REPORT.md` | **new** — the measured before/after tables (real numbers, this machine) |
| `tests/Stress_Tests/locustfile.py` | add a `check-in` task: the real `web → ai → db` path |

## Tests

| Type | File | Covers |
|---|---|---|
| Unit | `Unit_Tests/test_bench.py` | `cpu_burn` is deterministic, CPU-bound, scales with its work parameter, returns the contract shape |
| Integration | `Integration_Tests/test_scale_contract.py` | guards: scale override never publishes `ai`; `web` gets >1 worker; prod default target is the model, never the bench; the `/jobs`-vs-replicas caveat stays documented |
| Stress | `Stress_Tests/test_pool_scaling.py` | a real **process** pool with 4 workers beats 1 worker on CPU-bound work (skipped on a 1-core box) |
| Stress | `Stress_Tests/locustfile.py` | the authenticated check-in path drives `web → ai`, so the locust run measures the thing we scaled |

## Non-goals
Docker Swarm multi-machine (`DESIGN.md` names it as a *path*, not a deliverable). `web` replicas —
sessions are cookie-signed so it would work, but nothing in the rubric asks and the 1 GB VM cannot host
them.
