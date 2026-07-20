"""Unit tests for the AI job queue (GUIDELINES.md §2) — OWNER: Elad.

These test the queue's *bookkeeping*, which is what can silently rot: the depth bound, the reaping,
the counters, and what happens when the model raises. A thread pool is injected so the suite stays
fast — the pool type itself (a PROCESS pool, for real parallelism) is locked by
`Integration_Tests/test_ai_queue_contract.py`, not asserted here.

The worker target is redirected away from `inference:predict_one` per-test, so these never depend on
the model's placeholder body (Shiri may change it at will).
"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures.process import BrokenProcessPool

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
        kwargs.setdefault(
            "executor_factory", lambda: ThreadPoolExecutor(max_workers=workers)
        )
        queue = jobqueue_module.JobQueue(workers=workers, **kwargs)
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


# Id distinctness is pinned in Security_Tests/test_ai_queue.py::test_job_ids_are_not_sequential_or_guessable,
# which asserts distinctness plus uuid4 width, hex-not-counter, and no enumerable shared prefix.


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


# --------------------------------------------------------------------------- a BROKEN pool heals
#
# A ProcessPoolExecutor whose worker PROCESS dies (OOM, segfault) is permanently broken: every later
# `executor.submit()` raises BrokenProcessPool, and the pool never repairs itself. Before the heal
# logic, one dead worker therefore turned every subsequent /predict into a 500 until a human
# restarted the container — silently, because /health never touches the queue. These tests simulate
# the two ways the breakage surfaces: `submit()` raising, and an in-flight future resolving broken.


class BreakableExecutor:
    """Thread-pool stand-in for a process pool whose worker died: once `broken`, every submit
    raises BrokenProcessPool, exactly like the real executor's permanently-broken state."""

    def __init__(self, workers=2):
        self._pool = ThreadPoolExecutor(max_workers=workers)
        self.broken = False

    def submit(self, fn, *args, **kwargs):
        if self.broken:
            raise BrokenProcessPool("A child process terminated abruptly")
        return self._pool.submit(fn, *args, **kwargs)

    def shutdown(self, wait=True):
        self._pool.shutdown(wait=wait)


def test_a_pool_that_breaks_on_submit_is_replaced_and_the_submit_still_succeeds(make_queue):
    """One dead worker process must cost at most one job — never the whole container."""
    created = []

    def factory():
        executor = BreakableExecutor()
        created.append(executor)
        return executor

    queue = make_queue(executor_factory=factory)
    queue.result(queue.submit({"a": 1}), timeout=5)  # healthy pool works
    created[0].broken = True

    job_id = queue.submit({"b": 2})  # must heal the pool and retry, not raise
    assert queue.result(job_id, timeout=5)["seen"] == ["b"]
    assert len(created) == 2, "the broken executor was not replaced"
    assert queue.stats()["pool_rebuilds"] == 1


def test_a_submit_onto_a_broken_pool_leaks_no_capacity(make_queue):
    created = []

    def factory():
        executor = BreakableExecutor()
        created.append(executor)
        return executor

    queue = make_queue(executor_factory=factory, max_pending=2)
    created[0].broken = True
    queue.result(queue.submit({"a": 1}), timeout=5)  # healed + retried
    assert queue.stats()["pending"] == 0
    queue.submit({"b": 2})
    queue.submit({"c": 3})  # both slots must still exist


def test_a_worker_death_mid_job_rebuilds_the_pool_for_the_next_request(make_queue):
    """The done-callback path: the dying worker's own future resolves to BrokenProcessPool. That
    job is genuinely lost, but the NEXT submit must land on a fresh pool and succeed."""
    targets = iter([lambda f: (_ for _ in ()).throw(BrokenProcessPool("worker died")), echo])
    queue = make_queue(lambda features: next(targets)(features))

    dead = queue.submit({"a": 1})
    with pytest.raises(BrokenProcessPool):
        queue.result(dead, timeout=5)
    assert queue.stats()["pool_rebuilds"] == 1
    assert queue.stats()["pending"] == 0, "the lost job must still release its slot"

    good = queue.submit({"b": 2})
    assert queue.result(good, timeout=5)["seen"] == ["b"]


def test_two_jobs_dying_on_the_same_pool_rebuild_it_once_not_twice(make_queue):
    """N in-flight jobs all resolve BrokenProcessPool when one worker dies. The rebuild is
    generation-guarded so the second callback sees an already-replaced pool and leaves it alone —
    otherwise every casualty would throw away the fresh pool the previous one just built."""
    both_submitted = threading.Event()

    def die_together(features):
        both_submitted.wait(5)
        raise BrokenProcessPool("worker died")

    queue = make_queue(die_together, workers=2)
    first, second = queue.submit({"a": 1}), queue.submit({"b": 2})
    both_submitted.set()
    for job_id in (first, second):
        with pytest.raises(BrokenProcessPool):
            queue.result(job_id, timeout=5)
    assert queue.stats()["pool_rebuilds"] == 1


# --------------------------------------------------------------------------- hung workers
#
# A worker that HANGS (vs. dies) never completes its future, so nothing ever returns its depth
# slot: hang `max_pending` workers and the queue answers 503 forever. The hard wall-clock reaper
# abandons such jobs — releases the slot, settles waiters with a timeout — and replaces the pool
# outright once every worker is presumed hung.


def _stuck_target(release):
    """A worker that hangs until `release` is set — and an echo path for jobs that shouldn't."""

    def target(features):
        if features.get("stuck"):
            release.wait(10)
            return {"state": "late"}
        return echo(features)

    return target


def test_a_hung_job_releases_its_slot_after_the_hard_timeout(make_queue, jobqueue_module):
    release = threading.Event()
    queue = make_queue(_stuck_target(release), workers=2, max_pending=1, hard_timeout=0.05)
    hung = queue.submit({"stuck": True})
    with pytest.raises(jobqueue_module.QueueFull):
        queue.submit({"n": 1})  # the hung job holds the only slot

    # Reaping happens ON submit, so retry until it frees the slot rather than sleeping past the
    # hard timeout once: a single `sleep(hard_timeout + 0.01)` is a knife-edge on a loaded CI box
    # (the job may not have started yet), which made this file flaky under a full-suite run. The
    # assertion is unweakened — if the reaper never fires, every attempt stays QueueFull and the
    # test fails on `ok is None`.
    ok = None
    deadline = time.monotonic() + 5
    while ok is None and time.monotonic() < deadline:
        time.sleep(0.02)
        try:
            ok = queue.submit({"n": 2})
        except jobqueue_module.QueueFull:
            continue
    assert ok is not None, "the reaper never freed the hung job's slot within 5s"
    assert queue.result(ok, timeout=5)["seen"] == ["n"]
    assert queue.get(hung).status == "failed"
    assert "abandoned" in queue.get(hung).as_dict()["error"]
    assert queue.stats()["abandoned"] == 1
    release.set()


def test_waiting_on_an_abandoned_job_raises_a_timeout_not_a_hang(make_queue):
    release = threading.Event()
    queue = make_queue(_stuck_target(release), workers=2, hard_timeout=0.05)
    hung = queue.submit({"stuck": True})
    time.sleep(0.06)
    queue.submit({"n": 1})  # trigger the reap
    with pytest.raises(FutureTimeout):
        queue.result(hung, timeout=1)  # settled as failed — returns at once, no 1s wait
    release.set()


def test_an_abandoned_job_that_finishes_late_does_not_release_its_slot_twice(make_queue):
    """The reaper freed the slot already; if the 'hung' worker was merely slow and completes later,
    the done-callback must NOT decrement again — `pending` would go negative and backpressure would
    over-admit by one forever."""
    release = threading.Event()
    queue = make_queue(_stuck_target(release), workers=2, hard_timeout=0.05)
    queue.submit({"stuck": True})

    # Poll for the reap instead of sleeping exactly past the hard timeout — see the note in
    # test_a_hung_job_releases_its_slot_after_the_hard_timeout. Reaping runs on submit, so keep
    # submitting healthy jobs until the hung one is counted as abandoned.
    deadline = time.monotonic() + 5
    while queue.stats()["abandoned"] == 0 and time.monotonic() < deadline:
        time.sleep(0.02)
        queue.result(queue.submit({"n": 1}), timeout=5)
    assert queue.stats()["abandoned"] == 1, "the hung job was never reaped"
    assert queue.stats()["pending"] == 0

    release.set()  # the abandoned worker now finishes late
    deadline = time.monotonic() + 2
    while queue._abandoned and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not queue._abandoned, "the late completion was never observed"
    assert queue.stats()["pending"] == 0, "the late completion released the slot a second time"


def test_a_pool_with_every_worker_hung_is_replaced(make_queue):
    """Slot release alone is not enough when every pool worker is stuck: submits are accepted but
    nothing can score them. Once the presumed-hung count reaches the pool size, the pool itself is
    replaced so service resumes."""
    release = threading.Event()
    created = []

    def factory():
        executor = ThreadPoolExecutor(max_workers=1)
        created.append(executor)
        return executor

    queue = make_queue(
        _stuck_target(release), workers=1, max_pending=4, hard_timeout=0.05,
        executor_factory=factory,
    )
    queue.submit({"stuck": True})
    time.sleep(0.06)
    ok = queue.submit({"n": 1})  # reap: abandon + every worker presumed hung -> rebuild
    assert len(created) == 2, "the clogged pool was not replaced"
    assert queue.stats()["pool_rebuilds"] == 1
    assert queue.result(ok, timeout=5)["seen"] == ["n"]  # scored by the fresh pool
    release.set()  # unstick the leaked worker so teardown does not wait on it


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


def test_stats_are_settled_by_the_time_result_returns(make_queue, jobqueue_module, monkeypatch):
    """`result()` must not return while the job is still counted as pending.

    A future hands its value to the waiting thread and runs its done-callbacks *concurrently*, so
    waiting on the raw future let `/predict` answer while `pending` still counted the job as in
    flight — backpressure then over-admits. The window is microseconds wide, so this test widens it:
    the bookkeeping callback is delayed 100 ms, which is invisible to a `result()` that waits for the
    job to settle, and fatal to one that waits on the future.

    The job must still be RUNNING when its callback is registered, or the callback fires synchronously
    inside `submit()` and there is no window to observe.

    Without the delay this assertion flaked about one run in three, which is how the bug was found.
    """
    _delay_bookkeeping(jobqueue_module, monkeypatch)

    queue = make_queue(slow, workers=2)
    queue.result(queue.submit({"seconds": 0.15}), timeout=5)
    stats = queue.stats()
    assert stats["pending"] == 0, "result() returned before the depth counter was updated"
    assert stats["completed"] == 1, "result() returned before the job was recorded as complete"


def test_get_reports_a_settled_status_by_the_time_result_returns(make_queue, jobqueue_module, monkeypatch):
    """Same race, seen through `GET /jobs/<id>`: a caller that just read its result over `/predict`
    must never then be told the job is still 'queued'."""
    _delay_bookkeeping(jobqueue_module, monkeypatch)

    queue = make_queue(slow, workers=2)
    job_id = queue.submit({"seconds": 0.15})
    queue.result(job_id, timeout=5)
    assert queue.get(job_id).status == "done"


def _delay_bookkeeping(jobqueue_module, monkeypatch, delay=0.1):
    """Widen the race window: run the done-callback's bookkeeping `delay` seconds late."""
    original = jobqueue_module.JobQueue._on_done

    def slow_on_done(self, job_id, future):
        time.sleep(delay)
        original(self, job_id, future)

    monkeypatch.setattr(jobqueue_module.JobQueue, "_on_done", slow_on_done)


# `failed == 1` together with `pending == 0` after a raising worker is already asserted by
# test_stats_track_submitted_completed_and_failed above.


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


def test_env_var_sizes_the_hard_timeout(jobqueue_module, monkeypatch):
    monkeypatch.setenv("AI_JOB_HARD_TIMEOUT_SECONDS", "45.5")
    queue = jobqueue_module.JobQueue(executor_factory=lambda: ThreadPoolExecutor(max_workers=1))
    assert queue.hard_timeout == 45.5


@pytest.mark.parametrize("junk", ["", "abc", "0", "-3"])
def test_a_junk_hard_timeout_falls_back_to_the_default(jobqueue_module, monkeypatch, junk):
    monkeypatch.setenv("AI_JOB_HARD_TIMEOUT_SECONDS", junk)
    queue = jobqueue_module.JobQueue(executor_factory=lambda: ThreadPoolExecutor(max_workers=1))
    assert queue.hard_timeout == 120


def test_the_worker_target_is_resolved_by_name(jobqueue_module, monkeypatch):
    """The pool pickles the target by name, so it must resolve `module:attr` from a string."""
    monkeypatch.setenv("AI_WORKER_TARGET", "math:sqrt")
    queue = jobqueue_module.JobQueue(executor_factory=lambda: ThreadPoolExecutor(max_workers=1))
    assert queue.target == "math:sqrt"
    assert jobqueue_module._resolve_target("math:sqrt")(9) == 3


# DEFAULT_TARGET is pinned once, in
# Integration_Tests/test_ai_queue_contract.py::test_the_model_seam_exists_with_the_name_the_pool_resolves,
# which also resolves the string to the real callable — restating the constant here adds nothing.
