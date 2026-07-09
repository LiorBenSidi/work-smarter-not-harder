"""The claim behind the +5 and the scaling section, tested — OWNER: Elad.

Every other queue test injects a THREAD pool, because threads are fast and the queue's bookkeeping is
identical either way. That leaves one claim untested: that the production **process** pool actually
overlaps CPU-bound scoring across cores, which is the entire reason it is a process pool and not a
thread pool.

This is the test that would fail if someone swapped `ProcessPoolExecutor` for `ThreadPoolExecutor` and
all the mocked tests stayed green. It spawns real worker processes and runs real CPU-bound work
(`ai/bench.py:cpu_burn`), so it is slower than the rest of the suite — seconds, not milliseconds.

It is skipped on a single-core machine, where there is no parallelism to demonstrate and the assertion
would be a lie rather than a failure.
"""
import os
import sys
import time
from pathlib import Path

import pytest

# The worker processes resolve `bench:cpu_burn` by importing `bench`. `multiprocessing`'s spawn start
# method hands the child a copy of the parent's sys.path, so `ai/` has to be on it here — the
# container gets this for free from WORKDIR /app.
_AI = str(Path(__file__).resolve().parents[2] / "ai")
if _AI not in sys.path:
    sys.path.insert(0, _AI)

CORES = os.cpu_count() or 1

pytestmark = pytest.mark.skipif(CORES < 4, reason=f"needs >=4 cores to show pool scaling (have {CORES})")

# Sized so the WORK dominates: 8 x ~75 ms is ~0.6 s serial, well clear of process-spawn and IPC noise.
# At 300k the serial run was only ~0.18 s and a slow CI runner's jitter could swamp the signal.
ITERATIONS = 1_000_000
JOBS = 8


def _elapsed_with_pool(jobqueue_module, workers):
    """Submit JOBS identical CPU-bound jobs through a real process pool; return wall time."""
    queue = jobqueue_module.JobQueue(workers=workers, max_pending=JOBS * 2)
    queue.target = "bench:cpu_burn"
    queue.start()
    try:
        # Warm the pool: spawning workers and importing `bench` is a one-off cost that would
        # otherwise be charged to whichever configuration runs first.
        warmup = [queue.submit({"iterations": 1000}) for _ in range(workers)]
        for job_id in warmup:
            queue.result(job_id, timeout=120)

        started = time.perf_counter()
        job_ids = [queue.submit({"iterations": ITERATIONS}) for _ in range(JOBS)]
        results = [queue.result(job_id, timeout=180) for job_id in job_ids]
        elapsed = time.perf_counter() - started
    finally:
        queue.shutdown(wait=True)

    assert all(r["benchmark"] for r in results), "the pool did not run the benchmark workload"
    checksums = {r["checksum"] for r in results}
    assert len(checksums) == 1, "identical inputs produced different results — workload is not fixed"
    return elapsed


def test_a_four_worker_process_pool_beats_a_one_worker_pool_on_cpu_bound_work(jobqueue_module):
    """The +5 claim, measured: 8 identical CPU-bound jobs finish materially faster on 4 processes.

    The bar is deliberately modest (1.5x, not 4x): CI runners are shared and noisy, spawn costs are
    real, and a strict bound would flake. A thread pool would score ~1.0x here — it cannot beat 1.5x
    on pure-Python arithmetic, because the GIL serializes exactly this loop. So 1.5x separates "really
    parallel" from "not parallel" without pretending the speedup is linear.
    """
    serial = _elapsed_with_pool(jobqueue_module, workers=1)
    parallel = _elapsed_with_pool(jobqueue_module, workers=4)

    speedup = serial / parallel
    assert speedup > 1.5, (
        f"4 workers gave only {speedup:.2f}x over 1 worker "
        f"({serial:.2f}s -> {parallel:.2f}s) — the pool is not running work in parallel"
    )


def test_the_pool_returns_correct_results_under_parallel_load(jobqueue_module):
    """Parallelism must not corrupt answers: every job gets its own, matching its own input."""
    queue = jobqueue_module.JobQueue(workers=4, max_pending=32)
    queue.target = "bench:cpu_burn"
    queue.start()
    try:
        sizes = [1000, 2000, 3000, 4000] * 2
        job_ids = [queue.submit({"iterations": n}) for n in sizes]
        results = [queue.result(job_id, timeout=120) for job_id in job_ids]
    finally:
        queue.shutdown(wait=True)

    for requested, result in zip(sizes, results):
        assert result["iterations"] == requested, "a job came back with another job's workload"

    # ...and the same input always yields the same checksum, whichever worker ran it.
    by_size = {}
    for requested, result in zip(sizes, results):
        by_size.setdefault(requested, set()).add(result["checksum"])
    assert all(len(checksums) == 1 for checksums in by_size.values())
