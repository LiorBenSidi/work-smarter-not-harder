"""Stress: what the job queue does when it is overrun — OWNER: Elad.

The course rule for stress tests is "decide in advance what can crash, and defend it". For the `ai`
container the answer is the unbounded queue: a traffic spike grows the backlog until memory runs out,
and long before that the pool is burning cores on jobs whose callers already timed out. The defence is
backpressure — reject early, cheaply, and keep serving. VM size sets when it breaks, not whether.

These run in-process against a real `JobQueue` (thread-pool-backed, no Docker), so they belong in the
per-PR gate: they are seconds, not minutes. The minutes-long locust scenario against the live stack
lives in `locustfile.py`.
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest


def slow(features):
    time.sleep(features.get("seconds", 0.2))
    return {"state": "Moderate", "proba": {"Moderate": 1.0}, "recommendations": []}


@pytest.fixture
def flooded_queue(jobqueue_module, monkeypatch):
    created = []

    def _make(*, workers=2, max_pending=8, target=slow, **kwargs):
        monkeypatch.setattr(jobqueue_module, "_resolve_target", lambda _name: target)
        queue = jobqueue_module.JobQueue(
            workers=workers,
            max_pending=max_pending,
            executor_factory=lambda: ThreadPoolExecutor(max_workers=workers),
            **kwargs,
        )
        created.append(queue)
        return queue.start()

    yield _make
    for queue in created:
        # wait=True: a pool still draining after teardown would resolve its worker target through
        # the NEXT test's monkeypatch, and quietly run that test's function. Cross-test leak.
        queue.shutdown(wait=True)


def _flood(queue, jobqueue_module, count, features=None):
    """Submit `count` jobs, counting accepted vs shed. Never raises."""
    accepted, rejected = [], 0
    for _ in range(count):
        try:
            accepted.append(queue.submit(dict(features or {"seconds": 0.2})))
        except jobqueue_module.QueueFull:
            rejected += 1
    return accepted, rejected


def test_a_flood_is_shed_not_absorbed(flooded_queue, jobqueue_module):
    """4x the backlog arrives at once. The queue must accept its bound and reject the rest — not
    quietly grow to hold all of them."""
    queue = flooded_queue(max_pending=8)
    accepted, rejected = _flood(queue, jobqueue_module, 32)

    assert len(accepted) <= 8, "the queue absorbed more than its bound"
    assert rejected >= 24, "the queue did not shed the overflow"
    assert queue.stats()["pending"] <= 8


def test_the_in_flight_depth_never_exceeds_the_bound_under_concurrent_submitters(
    flooded_queue, jobqueue_module
):
    """The bound is checked and the slot reserved under one lock; without that, N threads racing
    past a `pending < max` read all get in and the ceiling is fiction."""
    queue = flooded_queue(workers=4, max_pending=6)
    breaches = []
    barrier = threading.Barrier(8)

    def submitter():
        barrier.wait()  # maximize the race
        for _ in range(10):
            try:
                queue.submit({"seconds": 0.05})
            except jobqueue_module.QueueFull:
                pass
            depth = queue.stats()["pending"]
            if depth > 6:
                breaches.append(depth)

    threads = [threading.Thread(target=submitter) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert not breaches, f"depth exceeded max_pending: {breaches}"


def test_the_queue_recovers_completely_after_the_flood(flooded_queue, jobqueue_module):
    """The failure that matters is a *permanent* wedge: if the depth counter leaks on rejection, the
    container serves 503 forever once it has been hit hard, and only a restart fixes it."""
    queue = flooded_queue(workers=4, max_pending=8)
    accepted, rejected = _flood(queue, jobqueue_module, 40, {"seconds": 0.02})
    assert rejected > 0, "the flood was not big enough to exercise rejection"

    for job_id in accepted:
        queue.result(job_id, timeout=10)

    assert queue.stats()["pending"] == 0, "depth leaked: the queue is permanently 'full'"
    assert queue.submit({"seconds": 0.01}), "the queue never accepted work again"


def test_rejections_are_cheap_and_do_not_spawn_work(flooded_queue, jobqueue_module):
    """A shed request must cost a lock and a counter — not a worker, not a job-store entry.
    Otherwise the flood we rejected still consumes the memory we were protecting."""
    executed = []

    def counting(features):
        executed.append(1)
        time.sleep(0.3)
        return {"state": "Moderate"}

    queue = flooded_queue(workers=1, max_pending=2, target=counting)
    accepted, rejected = _flood(queue, jobqueue_module, 20)

    assert rejected == 20 - len(accepted)
    assert queue.stats()["tracked_jobs"] <= 2, "rejected jobs must not enter the job store"
    time.sleep(0.05)
    assert len(executed) <= 1, "a rejected job must never reach a worker"


def test_a_flood_of_failing_jobs_does_not_wedge_the_queue(flooded_queue, jobqueue_module):
    """Worst case: the model is broken AND traffic spikes. Every job fails; capacity must still
    return, so the container recovers the moment the model does."""

    def always_fails(features):
        raise RuntimeError("model down")

    queue = flooded_queue(workers=2, max_pending=4, target=always_fails)
    accepted, _ = _flood(queue, jobqueue_module, 20)
    for job_id in accepted:
        with pytest.raises(RuntimeError):
            queue.result(job_id, timeout=5)

    assert queue.stats()["pending"] == 0
    assert queue.stats()["failed"] == len(accepted)
    assert queue.submit({"seconds": 0.01})


def test_the_job_store_stays_bounded_across_a_long_run(flooded_queue, jobqueue_module):
    """Sustained traffic inside one TTL window is the memory leak the TTL alone cannot catch."""
    queue = flooded_queue(workers=4, max_pending=8, max_jobs=10, job_ttl=3600)
    for _ in range(200):
        try:
            job_id = queue.submit({"seconds": 0.001})
        except jobqueue_module.QueueFull:
            time.sleep(0.005)
            continue
        queue.result(job_id, timeout=5)

    assert queue.stats()["tracked_jobs"] <= 18, queue.stats()


def test_health_keeps_returning_200_while_the_queue_is_saturated(ai_app_module, jobqueue_module, monkeypatch):
    """A busy container must not look like a dead one.

    `/health` is what Docker's healthcheck and the external uptime monitor poll. If it degraded while the
    queue was shedding — a 429 from a rate-limiter, or a 5xx because it touched the saturated queue — both
    would restart the container *because* it is busy, turning a load spike into a restart storm. So the
    invariant is: while `/predict` is correctly shedding 503, `/health` still answers 200.

    The queue is saturated directly rather than through concurrent HTTP calls: Flask's test client is not
    thread-safe, and filling the queue by hand makes the shed deterministic instead of timing-dependent.
    This is the HTTP-level counterpart to the queue-level shedding tests above — those prove the bound
    holds, this proves the liveness probe stays honest at the same moment. (Cited in REPORT.md §5.)
    """
    valid = {"sleep_hours": 8, "fatigue": 2, "soreness": 1, "training_load": 100}
    monkeypatch.setattr(jobqueue_module, "_resolve_target", lambda _name: slow)
    queue = jobqueue_module.JobQueue(
        workers=1, max_pending=2,
        executor_factory=lambda: ThreadPoolExecutor(max_workers=1),
    )
    app = ai_app_module.create_app(queue=queue)
    app.config["TESTING"] = True
    client = app.test_client()
    try:
        # Fill the one worker and both pending slots with long jobs, so the next submit must be rejected.
        for _ in range(3):
            try:
                queue.submit({"seconds": 5})
            except jobqueue_module.QueueFull:
                break

        shed = client.post("/predict", json={"features": dict(valid)})
        assert shed.status_code == 503, f"expected the queue to shed, got {shed.status_code}"

        # ...and while it is shedding, liveness must still be 200.
        health = client.get("/health")
        assert health.status_code == 200, f"/health degraded to {health.status_code} under load"
        assert health.get_json()["status"] == "ok"
    finally:
        queue.shutdown(wait=False)
