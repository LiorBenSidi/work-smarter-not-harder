"""A bounded job queue with a parallel worker pool, sitting in front of the model. OWNER: Elad.

Why this exists (GUIDELINES.md §2, +5): a single Flask process scores `/predict` calls one after
another. Under many concurrent users the model call — CPU-bound, and CPU-bound work does not overlap
across Python threads because of the GIL — serializes. This module puts a queue in front of it and
works the queue with a **process** pool, so N requests are scored on N cores at once.

Two properties matter more than throughput:

* **Bounded.** `max_pending` caps the in-flight depth. Past it, `submit()` raises `QueueFull` and the
  caller sheds load with 503. An unbounded queue under a flood trades a fast rejection for two slow
  failures: memory grows without limit, and the pool keeps scoring jobs whose callers timed out long ago.
  A larger VM raises the ceiling; it never makes the queue bounded.
* **Coherent.** The job store is in-memory and per-process, so the container runs ONE gunicorn worker
  (threads for concurrency, the pool for parallelism). See ai/Dockerfile.

The unit of work is resolved by name (`AI_WORKER_TARGET`, default `inference:predict_one`) rather than
passed in as a closure, because a process pool pickles the callable it is handed and closures do not
pickle. Resolving inside the child also keeps the pickled payload to the feature dict.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from concurrent.futures.process import BrokenProcessPool

logger = logging.getLogger(__name__)

QUEUED = "queued"
DONE = "done"
FAILED = "failed"

DEFAULT_TARGET = "inference:predict_one"


class QueueFull(Exception):
    """The queue is at capacity. Shed the request; do not grow the backlog."""


class JobNotFound(KeyError):
    """No job with that id (never submitted, or already reaped after its TTL)."""


def _resolve_target(target):
    module_name, _, attr = target.partition(":")
    return getattr(importlib.import_module(module_name), attr)


def _worker(target, features):
    """Runs in a worker process. Module-level so it pickles by name."""
    return _resolve_target(target)(features)


def _env_int(name, default):
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


def _env_float(name, default):
    try:
        value = float(os.environ.get(name, ""))
    except ValueError:
        return default
    return value if value > 0 else default


class Job:
    __slots__ = (
        "id", "status", "result", "error", "exception",
        "submitted_at", "finished_at", "settled", "generation",
    )

    def __init__(self, job_id):
        self.id = job_id
        self.status = QUEUED
        self.result = None
        self.error = None
        self.exception = None
        self.submitted_at = time.monotonic()
        self.finished_at = None
        # Which pool this job's work was submitted on. A BrokenProcessPool resolving this job may
        # only replace THAT pool: by the time the callback runs, a concurrent detection may already
        # have built a fresh one, which must not be thrown away in turn.
        self.generation = None
        # Set LAST, once the depth counter and the status have been updated. Waiters block on this
        # rather than on the raw future: `future.result()` can return before the future's done-callback
        # has run, which would let a caller observe a finished job with a stale `pending` count.
        self.settled = threading.Event()

    @property
    def finished(self):
        return self.status in (DONE, FAILED)

    def as_dict(self):
        payload = {"job_id": self.id, "status": self.status}
        if self.status == DONE:
            payload["result"] = self.result
        elif self.status == FAILED:
            payload["error"] = self.error
        return payload


class JobQueue:
    """Submit features, get them scored in parallel, read the result back by job id.

    `executor_factory` exists so tests can inject a thread pool: the queue's *bookkeeping* (bounding,
    reaping, counters, error capture) is identical either way, and threads keep the suite fast. The
    production default is a process pool — see `test_ai_queue_contract.py`, which asserts exactly that.
    """

    def __init__(
        self,
        *,
        workers=None,
        max_pending=None,
        job_ttl=None,
        max_jobs=None,
        hard_timeout=None,
        executor_factory=None,
    ):
        self.workers = workers or _env_int("AI_QUEUE_WORKERS", min(4, os.cpu_count() or 1))
        self.max_pending = max_pending or _env_int("AI_QUEUE_MAX_PENDING", 64)
        self.job_ttl = job_ttl or _env_int("AI_JOB_TTL_SECONDS", 300)
        self.max_jobs = max_jobs or _env_int("AI_MAX_JOBS", 1000)
        # The point past which an unfinished job is presumed HUNG and abandoned (its depth slot
        # released). Must exceed AI_PREDICT_TIMEOUT_SECONDS, or the reaper abandons jobs a caller
        # is still waiting on — `test_ai_queue_contract.py` pins that ordering.
        self.hard_timeout = hard_timeout or _env_float("AI_JOB_HARD_TIMEOUT_SECONDS", 120)
        self.target = os.environ.get("AI_WORKER_TARGET", DEFAULT_TARGET)

        self._executor_factory = executor_factory or (
            lambda: ProcessPoolExecutor(max_workers=self.workers)
        )
        self._executor = None
        self._lock = threading.Lock()
        self._jobs = OrderedDict()
        self._futures = {}
        self._pending = 0
        self._generation = 0
        # Ids whose depth slot the hard-timeout reaper already released. If such a worker turns out
        # to be finishing late rather than hung, its done-callback must not release the slot again.
        # NOT cleared when the job itself is forgotten: the entry is what protects the counter if
        # the future fires after the TTL reap. A future that truly never fires leaves its id here —
        # a few bytes per genuinely-hung worker, bounded by the pool-replacement escalation.
        self._abandoned = set()
        # How many of the CURRENT pool's workers are presumed stuck. At self.workers the pool can
        # score nothing at all, so it is replaced outright.
        self._suspect_hung = 0
        self._counters = {
            "submitted": 0, "completed": 0, "failed": 0, "rejected": 0,
            "abandoned": 0, "pool_rebuilds": 0,
        }

    # ---------------------------------------------------------------- lifecycle

    def start(self):
        """Idempotent: gunicorn may import the app module more than once per process."""
        with self._lock:
            if self._executor is None:
                self._executor = self._executor_factory()
                logger.info(
                    "job queue started: workers=%d max_pending=%d target=%s",
                    self.workers,
                    self.max_pending,
                    self.target,
                )
        return self

    def shutdown(self, wait=True):
        with self._lock:
            executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=wait)

    def _heal_locked(self, generation):
        """Replace the worker pool — called when it is BROKEN (a worker process died, so every
        later submit raises BrokenProcessPool forever) or fully clogged by presumed-hung workers.

        Generation-guarded: N concurrent detections of the same dead pool rebuild it once, and a
        stale detection can never throw away the fresh pool a previous one just built. Jobs still
        in flight on the old pool are not lost — `shutdown(wait=False)` lets running work finish
        (or, on a broken pool, resolve as failed), and each outcome flows through `_on_done` as
        usual. A truly hung worker process cannot be killed from here; the replacement restores
        service and the stuck process is leaked until the container restarts (REPORT.md §5.2).
        """
        if self._executor is None or generation != self._generation:
            return
        retired, self._executor = self._executor, self._executor_factory()
        self._generation += 1
        self._suspect_hung = 0
        self._counters["pool_rebuilds"] += 1
        retired.shutdown(wait=False)
        logger.error("worker pool replaced (generation %d)", self._generation)

    # ---------------------------------------------------------------- the queue

    def submit(self, features):
        """Enqueue one feature dict. Returns a job id. Raises `QueueFull` at capacity."""
        with self._lock:
            if self._executor is None:
                raise RuntimeError("job queue not started")
            self._reap_locked()
            if self._pending >= self.max_pending:
                self._counters["rejected"] += 1
                raise QueueFull(f"queue at capacity ({self.max_pending} pending)")

            job = Job(uuid.uuid4().hex)
            self._jobs[job.id] = job
            self._pending += 1
            self._counters["submitted"] += 1
            executor, generation = self._executor, self._generation

        # Submitted outside the lock: a pool that rejects the work (mid-shutdown) must not leave the
        # depth counter permanently inflated, so undo the reservation on failure. A BROKEN pool —
        # a worker process died — rejects every submission forever, so it is replaced and the
        # submit retried once on the fresh pool; without that, one dead worker turns every later
        # /predict into a 500 until a human restarts the container.
        for retried in (False, True):
            try:
                future = executor.submit(_worker, self.target, features)
                break
            except BrokenProcessPool:
                with self._lock:
                    self._heal_locked(generation)
                    executor, generation = self._executor, self._generation
                if retried or executor is None:
                    self._undo_reservation(job.id)
                    raise
            except Exception:
                self._undo_reservation(job.id)
                raise

        with self._lock:
            job.generation = generation
            self._futures[job.id] = future
        future.add_done_callback(lambda fut, job_id=job.id: self._on_done(job_id, fut))
        return job.id

    def _undo_reservation(self, job_id):
        """Roll back a submit that never handed work to a pool (call WITHOUT the lock held)."""
        with self._lock:
            self._pending -= 1
            self._jobs.pop(job_id, None)

    def _on_done(self, job_id, future):
        exception = None
        try:
            result = future.result()
        except BaseException as exc:  # noqa: BLE001 - a worker crash must not kill the callback thread
            status, payload, error, exception = FAILED, None, f"{type(exc).__name__}: {exc}", exc
            logger.warning("job %s failed: %s", job_id, error)
        else:
            status, payload, error = DONE, result, None

        with self._lock:
            job = self._jobs.get(job_id)
            if isinstance(exception, BrokenProcessPool) and job is not None:
                # A worker process died. The pool this job ran on is permanently broken — every
                # later submit onto it raises — so replace it. This job's result is lost either way.
                self._heal_locked(job.generation)
            if job_id in self._abandoned:
                # The hard-timeout reaper already released this job's slot and settled it as
                # failed; the worker was finishing late rather than hung. Releasing again would
                # drive `pending` negative and let backpressure over-admit forever.
                self._abandoned.discard(job_id)
                self._suspect_hung = max(0, self._suspect_hung - 1)
                return
            self._pending -= 1
            self._counters["completed" if status == DONE else "failed"] += 1
            if job is None:  # reaped while in flight (TTL far below the model's latency)
                return
            job.status = status
            job.result = payload
            job.error = error
            job.exception = exception
            job.finished_at = time.monotonic()

        job.settled.set()  # outside the lock: waiters wake and immediately take it to read stats

    def result(self, job_id, timeout=None):
        """Block for a job's result — the synchronous `/predict` path.

        Waits on the job's `settled` event rather than the raw future: a future hands its value to
        the waiting thread and runs its done-callbacks concurrently, so returning on the future alone
        would let `/predict` answer while `pending` still counted this job as in flight. Backpressure
        decisions read that counter, so it has to be true by the time a caller can observe it.

        Raises `JobNotFound`, `concurrent.futures.TimeoutError`, or whatever the worker raised.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFound(job_id)

        if not job.settled.wait(timeout):
            # The job keeps running — a timeout is the caller giving up, not a cancellation.
            raise FutureTimeout(f"job {job_id} did not finish within {timeout}s")
        if job.exception is not None:
            raise job.exception
        return job.result

    def get(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise JobNotFound(job_id)
            return job

    def stats(self):
        with self._lock:
            return {
                "workers": self.workers,
                "pending": self._pending,
                "max_pending": self.max_pending,
                "tracked_jobs": len(self._jobs),
                **self._counters,
            }

    # ---------------------------------------------------------------- reaping

    def _reap_locked(self):
        """Abandon presumed-hung jobs, drop finished jobs past their TTL, then trim to the cap.

        Without the TTL pass the job store is a memory leak with a slow fuse: every `/predict` adds
        an entry that nothing ever removes. In-flight jobs are never dropped by the TTL pass — but
        one that has produced nothing for `hard_timeout` is presumed HUNG and abandoned first:
        a hung worker (unlike a dead one) never completes its future, so nothing else would ever
        return its depth slot, and `max_pending` hangs would 503 every request forever.
        """
        hung_cutoff = time.monotonic() - self.hard_timeout
        for job_id, job in list(self._jobs.items()):
            if not job.finished and job.submitted_at < hung_cutoff:
                self._abandon_locked(job_id, job)
        if self._suspect_hung >= self.workers:
            # Every worker in the pool is presumed stuck: slots exist but nothing can score them.
            self._heal_locked(self._generation)

        cutoff = time.monotonic() - self.job_ttl
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.finished and job.finished_at is not None and job.finished_at < cutoff
        ]
        for job_id in expired:
            self._forget_locked(job_id)

        while len(self._jobs) > self.max_jobs:
            oldest = next(
                (job_id for job_id, job in self._jobs.items() if job.finished),
                None,
            )
            if oldest is None:  # everything tracked is still in flight — bounded by max_pending
                break
            self._forget_locked(oldest)

    def _abandon_locked(self, job_id, job):
        """Give up on a presumed-hung job: release its depth slot and settle its waiters.

        The future is deliberately NOT cancelled: a running worker cannot be cancelled anyway, and
        on a not-yet-started one `Future.cancel()` runs the done-callbacks synchronously in THIS
        thread — `_on_done` would then deadlock on the lock we are holding. If the work does run
        (or complete late) after all, `_on_done` finds the id in `_abandoned` and skips the second
        slot release.
        """
        job.status = FAILED
        job.error = f"abandoned: no result within {self.hard_timeout}s (worker presumed hung)"
        job.exception = FutureTimeout(job.error)
        job.finished_at = time.monotonic()
        self._pending -= 1
        self._counters["failed"] += 1
        self._counters["abandoned"] += 1
        self._suspect_hung += 1
        self._abandoned.add(job_id)
        job.settled.set()
        logger.error("job %s %s", job_id, job.error)

    def _forget_locked(self, job_id):
        self._jobs.pop(job_id, None)
        self._futures.pop(job_id, None)
