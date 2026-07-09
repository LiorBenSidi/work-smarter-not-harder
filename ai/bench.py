"""A CPU-bound stand-in for the model, used only to MEASURE scaling. OWNER: Elad.

Why this exists: the real `/predict` today is a placeholder that returns in microseconds, so a
before/after throughput table built on it would measure Flask and HTTP, not the pool — one worker
finishing instantly is exactly as fast as four. To show that the process pool actually overlaps work
across cores, the queue needs a unit of work that *costs* something, in the same seat the Random
Forest will occupy.

`cpu_burn` is that unit: pure Python arithmetic in a tight loop, which is precisely the shape the GIL
serializes and a process pool does not. It is selected by pointing the queue's existing
`AI_WORKER_TARGET` at it — no request path changes, same queue, same routes, same pool:

    AI_WORKER_TARGET=bench:cpu_burn  AI_QUEUE_WORKERS=4  docker compose up

It is **never the production target**. `jobqueue.DEFAULT_TARGET` is `inference:predict_one`, and
`tests/Integration_Tests/test_scale_contract.py` asserts the compose files never point `ai` here.

Deterministic on purpose: the same `iterations` always costs the same work and returns the same
number, so a before/after comparison changes only the worker count, never the workload.
"""
import logging
import os

logger = logging.getLogger(__name__)

DEFAULT_ITERATIONS = 200_000


def _iterations(features):
    """Per-request override (`features["iterations"]`), else `BENCH_ITERATIONS`, else the default."""
    requested = features.get("iterations")
    if isinstance(requested, int) and not isinstance(requested, bool) and requested > 0:
        return requested
    try:
        from_env = int(os.environ.get("BENCH_ITERATIONS", ""))
    except ValueError:
        return DEFAULT_ITERATIONS
    return from_env if from_env > 0 else DEFAULT_ITERATIONS


def cpu_burn(features):
    """Burn CPU deterministically, then answer in the `web -> ai` contract shape.

    The loop is deliberately pure Python (no NumPy): the point is to hold the GIL, so that a thread
    pool would serialize here and a process pool would not. Course L6 says vectorize a real hot loop —
    this one is a measuring instrument, not a hot path, and vectorizing it would defeat its purpose.
    """
    iterations = _iterations(features)
    total = 0
    for n in range(iterations):
        total = (total + n * n) % 1_000_003
    logger.debug("cpu_burn ran %d iterations -> %d", iterations, total)

    return {
        "state": "Moderate",
        "proba": {"Moderate": 1.0},
        "recommendations": [],
        "benchmark": True,
        "iterations": iterations,
        "checksum": total,
    }
