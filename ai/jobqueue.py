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


class Job:
    __slots__ = ("id", "status", "result", "error", "exception", "submitted_at", "finished_at", "settled")

    def __init__(self, job_id):
        self.id = job_id
        self.status = QUEUED
        self.result = None
        self.error = None
        self.exception = None
        self.submitted_at = time.monotonic()
        self.finished_at = None
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
        executor_factory=None,
    ):
        self.workers = workers or _env_int("AI_QUEUE_WORKERS", min(4, os.cpu_count() or 1))
        self.max_pending = max_pending or _env_int("AI_QUEUE_MAX_PENDING", 64)
        self.job_ttl = job_ttl or _env_int("AI_JOB_TTL_SECONDS", 300)
        self.max_jobs = max_jobs or _env_int("AI_MAX_JOBS", 1000)
        self.target = os.environ.get("AI_WORKER_TARGET", DEFAULT_TARGET)

        self._executor_factory = executor_factory or (
            lambda: ProcessPoolExecutor(max_workers=self.workers)
        )
        self._executor = None
        self._lock = threading.Lock()
        self._jobs = OrderedDict()
        self._futures = {}
        self._pending = 0
        self._counters = {"submitted": 0, "completed": 0, "failed": 0, "rejected": 0}

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
            executor = self._executor

        # Submitted outside the lock: a pool that rejects the work (mid-shutdown) must not leave the
        # depth counter permanently inflated, so undo the reservation on failure.
        try:
            future = executor.submit(_worker, self.target, features)
        except Exception:
            with self._lock:
                self._pending -= 1
                self._jobs.pop(job.id, None)
            raise

        with self._lock:
            self._futures[job.id] = future
        future.add_done_callback(lambda fut, job_id=job.id: self._on_done(job_id, fut))
        return job.id

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
            self._pending -= 1
            self._counters["completed" if status == DONE else "failed"] += 1
            job = self._jobs.get(job_id)
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
        """Drop finished jobs past their TTL, then trim the oldest if still over the cap.

        Without this the job store is a memory leak with a slow fuse: every `/predict` adds an entry
        that nothing ever removes. In-flight jobs are never dropped by the TTL pass.
        """
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

    def _forget_locked(self, job_id):
        self._jobs.pop(job_id, None)
        self._futures.pop(job_id, None)
