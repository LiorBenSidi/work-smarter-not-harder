# PLAN — AI Job Queue (+5) · OWNER: Elad

> Rubric source: [`GUIDELINES.md`](GUIDELINES.md) §2 — *"A **job queue** for the AI container so it handles
> **many requests at once from many users**, processed **in parallel**. A queue sits in front of the model so
> concurrent `/predict` calls are queued and worked in parallel rather than serialized."*

## Goal
Put a bounded queue + a parallel worker pool in front of the model inside the `ai` container, without
changing the `web → ai` contract and without taking over Shiri's model code.

## Shape

```
                     ai container (internal, no host port)
  web ──POST /predict──►  Flask (1 gunicorn worker, N threads)
                              │  submit(features)
                              ▼
                         JobQueue  ── bounded (max_pending) ──► shed load with 503
                              │
                              ▼
                    ProcessPoolExecutor(workers)   ← real parallelism (bypasses the GIL)
                              │
                              ▼
                    inference.predict_one(features)   ← Shiri's seam
```

## Files

| File | Owner | Change |
|---|---|---|
| `ai/jobqueue.py` | Elad | **new** — bounded queue, process pool, job store, TTL reaping, stats |
| `ai/inference.py` | Shiri (body) · Elad (seam) | **new** — `predict_one(features) -> dict`; placeholder body moved out of `app.py` verbatim |
| `ai/app.py` | Shiri | **~thin seam** — routes submit to the queue instead of computing inline |
| `ai/Dockerfile` | Elad | `--workers 1 --threads 8` (one job store per container) + queue env |
| `docker-compose*.yml` | Elad | queue env knobs; `AI_BASE_URL` for the test runner |

## API

`POST /predict` — **unchanged response shape** (`state` · `proba` · `recommendations`). Now enqueued and
worked by the pool; blocks for the result. `503` when the queue is full, `504` on timeout.

New, additive:
- `POST /jobs` → `202 {job_id, status}` — fire-and-forget enqueue.
- `GET /jobs/<id>` → `{job_id, status, result|error}`; `404` on unknown id.
- `GET /queue/stats` → depth, workers, counters (drives the locust before/after).

## Why one gunicorn worker
Each gunicorn worker would own a *separate* in-memory job store, so `POST /jobs` on worker A and
`GET /jobs/<id>` on worker B would 404 half the time. One worker + threads keeps the store coherent;
the **parallelism comes from the process pool**, which is what the rubric asks for (and it bypasses the
GIL for CPU-bound inference, unlike threads).

## Self-heal & hung workers (added after the pre-submission adversarial review)

Two failure modes the original design missed, both found by the team's adversarial review
(`presentation/For Elad - job queue robustness.md`) and closed here:

1. **A dead worker process wedges the pool forever.** `ProcessPoolExecutor` never recovers from a
   worker death: every later `submit()` raises `BrokenProcessPool`. The queue now **replaces the
   pool** when that surfaces — on submit (retried once on the fresh pool) or when an in-flight
   job's future resolves broken. The rebuild is *generation-guarded*: each job records which pool
   generation it ran on, so N jobs dying together rebuild once, and a stale detection can never
   throw away a fresh pool. Rebuilds are visible as `pool_rebuilds` in `/queue/stats`, and
   `/predict` maps a lost job to a retryable **503** instead of a 500.
2. **A hung worker leaks its depth slot.** A hang (unlike a death) never completes its future, so
   nothing returned the slot — `max_pending` hangs meant permanent 503. A **hard wall-clock
   reaper** (`AI_JOB_HARD_TIMEOUT_SECONDS`, default 120 s; a contract test pins it above the
   `/predict` deadline so it can never abandon a job a caller still waits on) runs in the existing
   reap pass: an unfinished job past the deadline is **abandoned** — slot released, waiters
   settled with a timeout, `abandoned` counted. If the worker was merely slow, its late completion
   is recognised (an `_abandoned` set) and does **not** release the slot twice. When *every* pool
   worker is presumed hung the pool is replaced outright.

Deliberate choices, so nobody "fixes" them later:
* **No `max_tasks_per_child`.** It recycles a worker only *between* tasks, so it cannot reclaim a
  hung one — and it forces the `spawn` start method, reloading the model on every respawn. It
  solves a problem we don't have and costs one we would.
* **No `Future.cancel()` on abandon.** A running task can't be cancelled anyway, and on a
  not-yet-started one `cancel()` runs the done-callbacks synchronously in the caller's thread —
  inside the queue's lock that is a self-deadlock. The abandoned-set makes the stray execution
  harmless instead.
* **A truly hung process is leaked, not killed.** The parent cannot safely kill a pool worker
  mid-IPC; the pool replacement restores service and the leak is bounded and stated in
  REPORT.md §5.2.

## Tests (all five types)

| Type | File | Covers |
|---|---|---|
| Unit | `Unit_Tests/test_jobqueue.py` | submit/result/get, bounded rejection, TTL reaping, job cap, stats counters, worker errors, idempotent start/shutdown, broken-pool self-heal, hung-worker abandonment |
| Integration | `Integration_Tests/test_ai_queue_api.py` | the four routes against the real Flask app, `/predict` shape preserved, 503/504/404 paths |
| Integration | `Integration_Tests/test_ai_queue_contract.py` | **guard tests** — lock the seam so a teammate's change breaks CI, not prod |
| System | `System_Tests/test_ai_queue_live.py` | real process pool over HTTP against the live `ai` container (compose harness) |
| Stress | `Stress_Tests/test_queue_backpressure.py` | flood → sheds with 503, never crashes, never unbounded |
| Security | `Security_Tests/test_ai_queue.py` | unguessable job ids, no cross-job leakage, oversized/hostile payloads rejected |

## Guard tests — what they protect (the point of the exercise)
A teammate editing `ai/app.py` or a compose file must not be able to silently undo this lane. The guards
assert, as cheap text/behaviour checks in the per-PR gate:

1. `/predict` still returns `state` + `proba` + `recommendations` (the `web → ai` contract).
2. `/predict` still goes **through the queue** (not a direct `predict_one` call in the route).
3. The queue stays **bounded** — an unbounded queue grows memory without limit and scores jobs whose
   callers already gave up. A bigger VM moves that cliff; it does not remove it.
4. `ai` still publishes **no host port**, in dev and in prod.
5. The Dockerfile still runs **one** gunicorn worker (job-store coherence) and the pool is a
   **process** pool (GIL bypass).
6. `inference.predict_one` still exists and is importable/picklable — Shiri may change its *body*
   freely; the queue only depends on its name and shape.

## Out of scope
The Random Forest itself (Shiri). `predict_one` keeps today's placeholder body verbatim; when the real
model lands it drops straight in with no queue change.
