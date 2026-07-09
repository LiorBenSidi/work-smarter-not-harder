"""Unit tests for the AI job queue (GUIDELINES.md §2) — OWNER: Elad.

These test the queue's *bookkeeping*, which is what can silently rot: the depth bound, the reaping,
the counters, and what happens when the model raises. A thread pool is injected so the suite stays
fast — the pool type itself (a PROCESS pool, for real parallelism) is locked by
`Integration_Tests/test_ai_queue_contract.py`, not asserted here.

The worker target is redirected away from `inference:predict_one` per-test, so these never depend on
the model's placeholder body (Shiri may change it at will).
"""
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

import pytest


# --------------------------------------------------------------------------- test doubles


def echo(features):
    """Stand-in for the model: returns something derived from its input, so a test can prove the
    features actually reached the worker rather than a cached/blank result coming back."""
    return {"state": "Moderate", "seen": sorted(features)}


def boom(features):
    raise ValueError("model exploded")


def slow(features):
    time.sleep(features["seconds"])
    return {"state": "Moderate"}


@pytest.fixture
def make_queue(jobqueue_module, monkeypatch):
    """Build a JobQueue whose worker runs `target` in a thread pool."""
    created = []

    def _make(target=echo, *, workers=4, **kwargs):
        monkeypatch.setattr(jobqueue_module, "_resolve_target", lambda _name: target)
        queue = jobqueue_module.JobQueue(
            workers=workers,
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


# --------------------------------------------------------------------------- the happy path


def test_submit_returns_an_id_and_result_carries_the_worker_output(make_queue):
    queue = make_queue()
    job_id = queue.submit({"hrv": 60, "sleep": 7})
    assert queue.result(job_id, timeout=5) == {"state": "Moderate", "seen": ["hrv", "sleep"]}


def test_get_reports_the_job_as_done_with_its_result(make_queue):
    queue = make_queue()
    job_id = queue.submit({"hrv": 60})
    queue.result(job_id, timeout=5)
    payload = queue.get(job_id).as_dict()
    assert payload["job_id"] == job_id
    assert payload["status"] == "done"
    assert payload["result"]["seen"] == ["hrv"]
    assert "error" not in payload


def test_each_submission_gets_a_distinct_id(make_queue):
    queue = make_queue()
    ids = {queue.submit({"n": n}) for n in range(20)}
    assert len(ids) == 20


def test_unknown_job_id_raises_job_not_found(make_queue, jobqueue_module):
    queue = make_queue()
    with pytest.raises(jobqueue_module.JobNotFound):
        queue.get("nope")
    with pytest.raises(jobqueue_module.JobNotFound):
        queue.result("nope")


# --------------------------------------------------------------------------- parallelism


def test_concurrent_jobs_overlap_instead_of_serializing(make_queue):
    """Four 0.3s jobs on four workers must finish in well under the 1.2s a serial queue would take.

    This is the whole point of the feature: without the pool, `/predict` calls queue up behind each
    other. The bound is loose (0.9s) so a slow CI runner does not flake it, but it is still far below
    the serial time.
    """
    queue = make_queue(slow, workers=4)
    started = time.monotonic()
    ids = [queue.submit({"seconds": 0.3}) for _ in range(4)]
    for job_id in ids:
        queue.result(job_id, timeout=10)
    elapsed = time.monotonic() - started
    assert elapsed < 0.9, f"jobs serialized: {elapsed:.2f}s for 4x0.3s on 4 workers"


# --------------------------------------------------------------------------- bounding / backpressure


def test_queue_rejects_once_max_pending_is_reached(make_queue, jobqueue_module):
    """The bound is the difference between shedding load and OOM-killing the container."""
    queue = make_queue(slow, workers=1, max_pending=2)
    queue.submit({"seconds": 0.4})
    queue.submit({"seconds": 0.4})
    with pytest.raises(jobqueue_module.QueueFull):
        queue.submit({"seconds": 0.4})


def test_capacity_frees_up_again_once_jobs_finish(make_queue, jobqueue_module):
    """A full queue must be a transient state, not a permanently wedged one — i.e. the pending
    counter is decremented on completion, not just incremented on submit."""
    queue = make_queue(slow, workers=1, max_pending=1)
    first = queue.submit({"seconds": 0.05})
    with pytest.raises(jobqueue_module.QueueFull):
        queue.submit({"seconds": 0.05})
    queue.result(first, timeout=5)
    assert queue.submit({"seconds": 0.01})  # capacity returned


def test_a_failing_worker_also_frees_capacity(make_queue, jobqueue_module):
    """If the model raises, the slot must still be released — otherwise a burst of model errors
    permanently wedges the queue at 'full' and every later request 503s."""
    queue = make_queue(boom, workers=1, max_pending=1)
    job_id = queue.submit({"hrv": 1})
    with pytest.raises(ValueError):
        queue.result(job_id, timeout=5)
    assert queue.stats()["pending"] == 0
    assert queue.submit({"hrv": 2})


def test_rejections_are_counted(make_queue, jobqueue_module):
    queue = make_queue(slow, workers=1, max_pending=1)
    queue.submit({"seconds": 0.3})
    with pytest.raises(jobqueue_module.QueueFull):
        queue.submit({"seconds": 0.3})
    assert queue.stats()["rejected"] == 1


# --------------------------------------------------------------------------- worker failure


def test_a_raising_worker_marks_the_job_failed_with_the_error(make_queue):
    queue = make_queue(boom)
    job_id = queue.submit({"hrv": 60})
    with pytest.raises(ValueError):
        queue.result(job_id, timeout=5)
    payload = queue.get(job_id).as_dict()
    assert payload["status"] == "failed"
    assert "model exploded" in payload["error"]
    assert "result" not in payload


def test_one_failing_job_does_not_poison_the_next(make_queue, jobqueue_module):
    """A worker exception must be captured per-job, not tear down the pool."""
    targets = iter([boom, echo])
    queue = make_queue(lambda features: next(targets)(features))
    bad = queue.submit({"a": 1})
    with pytest.raises(ValueError):
        queue.result(bad, timeout=5)
    good = queue.submit({"b": 2})
    assert queue.result(good, timeout=5)["seen"] == ["b"]


# --------------------------------------------------------------------------- timeouts


def test_result_times_out_without_losing_the_job(make_queue):
    queue = make_queue(slow, workers=1)
    job_id = queue.submit({"seconds": 0.5})
    with pytest.raises(FutureTimeout):
        queue.result(job_id, timeout=0.01)
    # the job keeps running and still lands — a timeout is the caller giving up, not a cancellation
    assert queue.result(job_id, timeout=5)["state"] == "Moderate"


# --------------------------------------------------------------------------- reaping / memory


def test_finished_jobs_are_reaped_once_past_their_ttl(make_queue, jobqueue_module):
    """Without reaping the job store is a slow memory leak: one entry per /predict, forever."""
    queue = make_queue(job_ttl=1)
    old = queue.submit({"a": 1})
    queue.result(old, timeout=5)
    queue.job_ttl = 0.01  # age it out without sleeping the suite
    time.sleep(0.02)
    queue.submit({"b": 2})  # reaping happens on submit
    with pytest.raises(jobqueue_module.JobNotFound):
        queue.get(old)


def test_reaping_never_drops_a_job_that_is_still_running(make_queue):
    queue = make_queue(slow, workers=2, job_ttl=1)
    in_flight = queue.submit({"seconds": 0.4})
    queue.job_ttl = 0.001
    time.sleep(0.01)
    queue.submit({"seconds": 0.01})  # triggers a reap while `in_flight` is unfinished
    assert queue.get(in_flight).status == "queued"
    assert queue.result(in_flight, timeout=5)["state"] == "Moderate"


def test_the_job_store_is_capped_even_when_nothing_has_expired(make_queue):
    """TTL alone does not bound memory: a burst inside one TTL window can still be unbounded."""
    queue = make_queue(max_jobs=5, job_ttl=3600)
    for n in range(20):
        job_id = queue.submit({"n": n})
        queue.result(job_id, timeout=5)
    queue.submit({"n": "last"})
    assert queue.stats()["tracked_jobs"] <= 6  # the cap, plus the just-submitted job


# --------------------------------------------------------------------------- stats / lifecycle


def test_stats_track_submitted_completed_and_failed(make_queue):
    targets = iter([echo, echo, boom])
    queue = make_queue(lambda features: next(targets)(features))
    for _ in range(2):
        queue.result(queue.submit({"a": 1}), timeout=5)
    with pytest.raises(ValueError):
        queue.result(queue.submit({"a": 1}), timeout=5)
    stats = queue.stats()
    assert stats["submitted"] == 3
    assert stats["completed"] == 2
    assert stats["failed"] == 1
    assert stats["pending"] == 0


def test_stats_expose_the_bound_so_operators_can_see_headroom(make_queue):
    queue = make_queue(workers=3, max_pending=7)
    stats = queue.stats()
    assert stats["workers"] == 3
    assert stats["max_pending"] == 7


def test_submitting_before_start_is_a_programming_error(jobqueue_module):
    queue = jobqueue_module.JobQueue(executor_factory=lambda: ThreadPoolExecutor(max_workers=1))
    with pytest.raises(RuntimeError):
        queue.submit({"a": 1})


def test_start_is_idempotent(make_queue):
    """gunicorn can import the app module more than once in a worker; a second start() must not
    orphan the first pool."""
    queue = make_queue()
    first = queue._executor
    queue.start()
    assert queue._executor is first


def test_shutdown_is_idempotent(make_queue):
    queue = make_queue()
    queue.shutdown()
    queue.shutdown()  # must not raise


# --------------------------------------------------------------------------- configuration


def test_env_vars_size_the_queue(jobqueue_module, monkeypatch):
    monkeypatch.setenv("AI_QUEUE_WORKERS", "6")
    monkeypatch.setenv("AI_QUEUE_MAX_PENDING", "9")
    queue = jobqueue_module.JobQueue(executor_factory=lambda: ThreadPoolExecutor(max_workers=1))
    assert queue.workers == 6
    assert queue.max_pending == 9


@pytest.mark.parametrize("junk", ["", "abc", "0", "-3"])
def test_a_junk_env_value_falls_back_to_the_default_instead_of_crashing(
    jobqueue_module, monkeypatch, junk
):
    """A typo'd env var on the VM must not produce a zero-worker pool or an unbounded queue."""
    monkeypatch.setenv("AI_QUEUE_MAX_PENDING", junk)
    queue = jobqueue_module.JobQueue(executor_factory=lambda: ThreadPoolExecutor(max_workers=1))
    assert queue.max_pending == 64


def test_the_worker_target_is_resolved_by_name(jobqueue_module, monkeypatch):
    """The pool pickles the target by name, so it must resolve `module:attr` from a string."""
    monkeypatch.setenv("AI_WORKER_TARGET", "math:sqrt")
    queue = jobqueue_module.JobQueue(executor_factory=lambda: ThreadPoolExecutor(max_workers=1))
    assert queue.target == "math:sqrt"
    assert jobqueue_module._resolve_target("math:sqrt")(9) == 3


def test_the_default_target_is_the_model_seam(jobqueue_module):
    assert jobqueue_module.DEFAULT_TARGET == "inference:predict_one"
