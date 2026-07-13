# Scaling report — measured before/after

> **Rubric:** [`GUIDELINES.md`](GUIDELINES.md) §4 — the deployed site must be *"public and scalable via
> parallelization"*; §2 (+5) — a job queue works `/predict` in parallel.
> **Design contract:** [`DESIGN.md`](DESIGN.md) §L7 — *"a locust run before/after `--scale ai=2` shows
> throughput rising."*
> **Owner:** Elad · **Measured:** 2026-07-09 · **Plan:** [`SCALING_PLAN.md`](SCALING_PLAN.md)

## How this was measured, and why it is honest

The shipped model is a **placeholder that returns in microseconds**. Any throughput table built on it
would measure Flask and HTTP, not the pool: one worker finishing instantly is exactly as fast as four,
and a "2× speedup" would be measurement noise dressed up as a result.

So every number below was taken with a **CPU-bound workload in the same seat the Random Forest will
occupy** — `ai/bench.py:cpu_burn`, a deterministic pure-Python arithmetic loop, selected through the
queue's existing `AI_WORKER_TARGET` env var. Nothing else changes: same routes, same queue, same pool,
same request path. Only the function at the bottom differs.

`cpu_burn` is **never the production target** (`inference:predict_one` is the default, and
[`test_scale_contract.py`](../tests/Integration_Tests/test_scale_contract.py) asserts no shipped compose
file points `ai` at the benchmark).

**Load generator:** [`scripts/scaling_benchmark.py`](../scripts/scaling_benchmark.py) — stdlib only, so it
runs on the VM and in CI without installing locust. Each run warms the pool first (process spawn and
import are one-off costs that would otherwise be charged to whichever configuration ran first), then
issues 120 requests at concurrency 8. `tests/Stress_Tests/locustfile.py` drives the identical endpoint
under `LOCUST_TARGET=ai` for the ramped version of the same experiment.

**Machine:** 8 logical cores, Docker Desktop (Windows), `ai` container capped at `--cpus=4`,
`BENCH_ITERATIONS=200000`, 120 requests @ concurrency 8.

---

## Axis 1 — Vertical: the process pool inside one container

`AI_QUEUE_WORKERS` sizes the `ProcessPoolExecutor` that works the queue.

| `AI_QUEUE_WORKERS` | Throughput (req/s) | p50 (ms) | p95 (ms) | Wall (s) | Failures |
|---|---|---|---|---|---|
| 1 (before) | 88.63 | 88.1 | 104.0 | 1.354 | 0 |
| 4 (after) | **253.40** | 28.2 | 51.4 | 0.474 | 0 |

**2.86× throughput**, and p95 latency *halved* (104 ms → 51 ms). The latency column matters: a
throughput gain paid for by a latency collapse is not a gain. Here both improved, which is what genuine
parallelism looks like — the work is spread, not merely buffered.

The gain is 2.86×, not 4×, because the container is capped at 4 CPUs that it shares with gunicorn's
threads and the OS, and because each job pays a small pickle round-trip to its worker process.

## Axis 2 — Horizontal: `--scale ai=N` replicas

Each container runs a 1-worker pool, so this isolates the *replica* effect. `web` reaches `ai` by its
Docker service DNS name, which round-robins across replicas — no `web` config change, no load balancer.
Measured from inside the compose network (exactly how `web` calls it):

```sh
docker compose -f docker-compose.yml -f docker-compose.scale.yml up -d --build --scale ai=2
```

| `ai` replicas | Throughput (req/s) | p50 (ms) | p95 (ms) | Wall (s) | Failures |
|---|---|---|---|---|---|
| 1 (before) | 91.27 | 86.1 | 96.0 | 1.315 | 0 |
| 2 (after) | **146.25** | 51.8 | 92.8 | 0.821 | 0 |

**1.60× throughput.** Sub-linear on purpose to report, not to hide: Docker's DNS round-robin balances
*connections*, not *work*, so with only 8 concurrent clients the split is uneven, and p95 barely moves
(96 → 93 ms) because the tail is set by whichever replica got the unlucky burst. Throughput scales;
tail latency needs a real load balancer, which the single course VM does not warrant.

The two axes **multiply**: total parallel scorers = `AI_QUEUE_WORKERS` × replicas.

## Axis 3 — Why a *process* pool, not threads

The queue could have used a `ThreadPoolExecutor` and every mocked test in the suite would still pass.
It would also have scaled to nothing. Measured directly, 8 identical CPU-bound jobs, 1 worker vs 4:

| Pool type | Speedup (4 workers vs 1) |
|---|---|
| `ProcessPoolExecutor` (shipped) | **3.58×** |
| `ThreadPoolExecutor` (mutation) | 0.96× |

0.96× is the GIL: pure-Python arithmetic cannot overlap across threads, so four threads do the same
work as one and pay for the context switching. This is not a thought experiment — it was produced by
swapping the executor and re-running
[`test_pool_scaling.py`](../tests/Stress_Tests/test_pool_scaling.py), which fails at `0.957 > 1.5` on
the thread pool and passes on processes. That test is the standing guard against someone "simplifying"
the pool back to threads.

---

## Reproducing

```sh
# Axis 1 — vertical (one container, pool size varies)
docker build -t wsnh-ai ./ai
docker run -d --name ai-bench --cpus=4 -p 5099:5000 \
  -e AI_WORKER_TARGET=bench:cpu_burn -e AI_QUEUE_WORKERS=1 -e BENCH_ITERATIONS=200000 wsnh-ai
python scripts/scaling_benchmark.py --url http://localhost:5099/predict --label pool=1
# ...repeat with AI_QUEUE_WORKERS=4

# Axis 2 — horizontal (replicas, driven from inside the compose network like web does)
AI_WORKER_TARGET=bench:cpu_burn AI_QUEUE_WORKERS=1 \
  docker compose -f docker-compose.yml -f docker-compose.scale.yml up -d --build --scale ai=2 ai
docker run --rm --network work-smarter-not-harder_default -v "$PWD/scripts:/bench:ro" python:3.12-slim \
  python /bench/scaling_benchmark.py --url http://ai:5000/predict --label replicas=2

# The ramped locust version of Axis 1/2
LOCUST_TARGET=ai locust -f tests/Stress_Tests/locustfile.py --headless -u 8 -r 8 -t 30s \
  --host http://localhost:5099 --exit-code-on-error 1
```

## The replica caveat (read before scaling out)

`ai`'s job store is **in-memory, per container**:

* `POST /predict` is **replica-safe** — one request, one response, nothing read back later. This is the
  only endpoint `web` calls, so `--scale ai=N` is safe today.
* `POST /jobs` + `GET /jobs/<id>` are **not** — the follow-up GET round-robins to a replica that never
  saw the job, so it 404s roughly (N−1)/N of the time.

Making `/jobs` replica-safe means an external store (Redis / Mongo) for job state. That is a real
option, not a defect: the synchronous `/predict` path the app actually uses needs none of it, and
adding Redis would put a fourth container — a new dependency, a new failure mode — in front of an
endpoint nothing calls. Documented in `docker-compose.scale.yml`, in `ai/jobqueue.py`, and asserted
by `test_scale_contract.py`.

## What this does not cover

* **Multi-machine (Docker Swarm overlay).** `DESIGN.md` names it as a *path*; the containers are
  stateless so `docker stack deploy` would work, but the course supplies one VM.
* **`web` replicas.** Sessions are cookie-signed, so `web` would scale horizontally, and the resized VM
  has the RAM for it. Not done, on purpose: `web` is I/O-bound (it waits on Mongo and `ai`, and those
  socket waits release the GIL), so widening the **thread** pool inside one gthread worker buys the same
  concurrency more cheaply than a second process — and on a single VM, replicas of `web` add throughput,
  never availability.
* **Prod now runs these numbers, not smaller ones.** The VM was resized mid-project from a ~1 GB B1s to a
  **Standard E4ads v5 (4 vCPU / 32 GiB)**, so prod pins `AI_QUEUE_WORKERS=4` — one per vCPU, each pool
  process holding its own copy of the model. The old 1 GB cap forced `AI_QUEUE_WORKERS=2` and could not.
  The benchmark above capped the `ai` container at `--cpus=4`, so prod's core count now **matches the
  measured configuration** and the 2.86× is the number prod should actually see — not a lab-only figure.
  `AI_QUEUE_MAX_PENDING=32` stays: the backlog bound is about shedding load before callers time out, not
  about fitting in RAM.

## Measured model footprint — the real RF validates the sizing (#248)

The numbers above are the *scaling* measurement (the CPU-bound bench target, so throughput reflects the
pool). Once the real Random Forest was baked into the image, Shiri measured its footprint directly inside
the container (50 warm-up + 1,000 measured `predict_one` calls — issue #248, 2026-07-12):

| Metric | Measured |
|---|---|
| RSS after loading inference + model | 161.73 MB / process |
| Model-import RAM increase | 149.61 MB / process |
| Prediction latency — mean / median | 26.95 ms / 26.61 ms |
| Prediction latency — p95 / max | 32.45 ms / 75.89 ms |

A second in-container measurement (Shiri, 2026-07-13, 1,000 `predict_one` calls) reproduced the footprint
from a fresh sample: **33.6 ms mean latency · 159.24 MB total process RSS (+151.11 MB import/load delta)**.
The latency runs a little higher than the #248 mean — a slower / more-loaded run, it even sits above the
#248 p95 — but it lands on the same sizing conclusion, which is the point of an independent re-measure. Both
runs are on record; the reasoning below uses the #248 distribution and holds a fortiori at 33.6 ms. In
particular `AI_CLIENT_TIMEOUT`=33 s stays as set — ~980× the measured mean — validated against both
measurements rather than guessed.

These confirm the production knobs; **no retune was needed**:

* **`AI_QUEUE_WORKERS=4` is RAM-safe.** Each pool process holds its own model copy, so the pool costs
  ~4 × 162 MB ≈ **0.65 GB** — about 2 % of the E4ads v5's 32 GiB. Four workers (one per vCPU) is the
  right ceiling for CPU-bound scoring, and RAM is nowhere near the limit.
* **Every timeout in the chain sits 100–1500× above the measured latency**, so a healthy prediction can
  never trip a deadline. In order: `AI_PREDICT_TIMEOUT_SECONDS`=30 s (the queue wait — ~395× the 76 ms
  max) < `AI_CLIENT_TIMEOUT`=33 s (web's wait) < web gunicorn `--timeout` 45 s; on the `ai` side the
  gunicorn `--timeout` 60 s and the hung-worker reaper `AI_JOB_HARD_TIMEOUT_SECONDS`=120 s both clear the
  30 s deadline (guard-pinned). A deadline only fires on a genuinely wedged worker, never a slow-but-live one.
* **`AI_QUEUE_MAX_PENDING=32` is comfortable.** At ~27 ms/predict, four workers clear ~148 predictions/s,
  so a full 32-deep backlog drains in ≈ 0.22 s — the worst-case fully-queued `/predict` still answers
  ~100× inside its 30 s deadline. The bound sheds load long before callers time out.

Shiri's caveat at measurement time — "this covers the Random Forest inference only; the recommendation
engine is not built yet, re-measure when it lands" — is now closed. The engine landed with the model merge
(`ai/recommendations.py`: rule-based state/feature lookups + a calorie estimate, no model call), and the
promised re-measure (10,000 calls per state, 2026-07-13) puts it at **~2.5 µs per
`generate_recommendations` call + ~1.7 µs per `calculate_calories` call, worst observed spike 240 µs** —
four orders of magnitude below the ~27 ms RF inference it rides on. It moves `predict_one`'s latency by
roughly 0.01 %, so every headroom figure above stands unchanged and **the knobs stay as they are**.
