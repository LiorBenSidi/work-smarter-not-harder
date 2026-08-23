"""Job-queue contract guards — OWNER: Elad.

The queue (GUIDELINES.md §2, +5) lives inside a container whose model code belongs to Shiri and whose
compose/prod wiring is shared. This file locks the handful of invariants that a well-meaning change
elsewhere can silently undo, so the breakage surfaces as a red CI run on the PR instead of as a dead
or OOM-killed `ai` container after a merge:

  * the `web -> ai` contract: `/predict` still answers `state` + `proba` + `recommendations`;
  * `/predict` still goes THROUGH the queue (not straight to the model — that re-serializes it and
    silently forfeits the +5);
  * the queue stays BOUNDED (an unbounded backlog grows memory without limit and scores jobs whose
    callers already timed out — a bigger VM moves that cliff, it does not remove it);
  * the pool is a PROCESS pool (threads do not overlap CPU-bound inference — the GIL);
  * exactly ONE gunicorn worker serves `ai` (a second one owns a second in-memory job store, so
    `GET /jobs/<id>` would 404 whenever it landed on the wrong worker);
  * that worker's gunicorn `--timeout` EXCEEDS the queue's own deadline (otherwise gunicorn SIGKILLs
    the worker mid-wait and `/predict`'s 504 degrade is unreachable);
  * `inference.predict_one` still exists with the shape the pool expects. Shiri owns its BODY and may
    change it freely — these guards only pin its name and its return keys.
  * `ai` still publishes no host port, in dev and in prod.

Most are cheap text/introspection assertions (no Docker, no live stack), so they run in the normal
per-PR gate alongside `test_deploy_contract.py`.
"""
import inspect
import pickle
import re
import threading
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from multiprocessing import get_context
from pathlib import Path

import pytest


def _spawn_pool(workers):
    """A ProcessPoolExecutor that starts its workers with SPAWN, not the Linux default FORK (#605).

    The suite runs pytest multi-threaded; fork() copies a held lock into a worker, which can wedge,
    and ProcessPoolExecutor's atexit reaper joins that worker with NO timeout -> the interpreter hangs
    for up to the 6h CI ceiling. SPAWN starts a fresh interpreter (no inherited locks), so the pool
    joins cleanly. Injected only in the tests that create a REAL process pool; production keeps its
    fork default (deliberately unchanged before submission -- see #605)."""
    return lambda: ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn"))

ROOT = Path(__file__).resolve().parents[2]


def _strip_comments(text):
    """Drop `#` comments so a directive named in prose can never satisfy — or trip — an assertion."""
    lines = []
    for line in text.splitlines():
        code = line.split("#", 1)[0].rstrip()
        if code:
            lines.append(code)
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def ai_source():
    return (ROOT / "ai" / "app.py").read_text()


@pytest.fixture(scope="module")
def dockerfile():
    return _strip_comments((ROOT / "ai" / "Dockerfile").read_text())


@pytest.fixture(scope="module")
def prod():
    return _strip_comments((ROOT / "docker-compose.prod.yml").read_text())


@pytest.fixture(scope="module")
def dev():
    return _strip_comments((ROOT / "docker-compose.yml").read_text())


# --------------------------------------------------------------------------- the model seam


def test_the_model_seam_exists_with_the_name_the_pool_resolves(inference_module, jobqueue_module):
    """The pool imports the target by string. Renaming `predict_one` breaks scoring at RUNTIME, in a
    worker process, where the traceback is easy to miss — so pin it here instead."""
    assert jobqueue_module.DEFAULT_TARGET == "inference:predict_one"
    assert callable(inference_module.predict_one)
    resolved = jobqueue_module._resolve_target("inference:predict_one")
    assert resolved is inference_module.predict_one


def test_the_model_seam_takes_exactly_one_features_argument(inference_module):
    signature = inspect.signature(inference_module.predict_one)
    assert list(signature.parameters) == ["features"]


def test_the_model_seam_returns_the_web_ai_contract_keys(inference_module):
    """Shiri owns the VALUES; `web/services/ai_client.py` reads these KEYS.

    Call with the four fields the real Random Forest requires (sleep_hours, fatigue, soreness,
    training_load) — Shiri's model raises ValueError on incomplete input rather than
    median-imputing invented values, so an under-specified call here would fail for the wrong reason.
    """
    result = inference_module.predict_one(
        {"sleep_hours": 8, "fatigue": 2, "soreness": 1, "training_load": 100}
    )
    assert {"state", "proba", "recommendations"} <= set(result)
    assert isinstance(result["state"], str)
    assert isinstance(result["proba"], dict)
    assert isinstance(result["recommendations"], list)


def test_the_model_seam_is_picklable_by_reference(inference_module):
    """A ProcessPoolExecutor pickles the callable by qualified name. If `predict_one` becomes a
    closure, a bound method, or a lambda, every job dies with a PicklingError inside the worker."""
    assert pickle.loads(pickle.dumps(inference_module.predict_one)) is inference_module.predict_one


def test_the_model_seam_result_is_picklable(inference_module):
    """The worker's return value crosses a process boundary, so it must pickle too — a numpy scalar
    or a fitted-estimator handle sneaking into the response would only fail in production."""
    result = inference_module.predict_one(
        {"sleep_hours": 8, "fatigue": 2, "soreness": 1, "training_load": 100}
    )
    assert pickle.loads(pickle.dumps(result)) == result


def test_the_model_lives_outside_the_request_handler(ai_source):
    """Inference belongs in `inference.py` (importable by a worker process), not inlined in a Flask
    route where the pool can never reach it."""
    assert "from jobqueue import" in ai_source
    assert "def predict_one" not in ai_source, "the model seam must stay in ai/inference.py"


# --------------------------------------------------------------------------- the queue is used


def test_predict_goes_through_the_queue(ai_source):
    """The whole feature: `/predict` enqueues instead of scoring inline. A direct `predict_one(...)`
    call in the route would keep every test green while serializing every request."""
    route = ai_source.split("def predict()", 1)[1].split("@app.", 1)[0]
    assert "queue.submit(" in route, "/predict must enqueue the work"
    assert "predict_one(" not in route, "/predict must not call the model directly"


def test_predict_sheds_load_rather_than_queueing_without_limit(ai_source):
    route = ai_source.split("def predict()", 1)[1].split("@app.", 1)[0]
    assert "QueueFull" in route and "503" in route, "a full queue must shed with 503"


def test_predict_bounds_how_long_it_will_wait(ai_source):
    """An unbounded `future.result()` pins a gunicorn thread forever on a wedged model."""
    route = ai_source.split("def predict()", 1)[1].split("@app.", 1)[0]
    assert "timeout=" in route and "504" in route


def test_the_async_job_routes_exist(ai_source):
    assert '@app.post("/jobs")' in ai_source
    assert '@app.get("/jobs/<job_id>")' in ai_source
    assert '@app.get("/queue/stats")' in ai_source


# --------------------------------------------------------------------------- the queue is bounded


def test_the_queue_defaults_to_a_finite_backlog(jobqueue_module):
    queue = jobqueue_module.JobQueue(executor_factory=lambda: ThreadPoolExecutor(max_workers=1))
    assert 0 < queue.max_pending < 10_000, "the backlog must be bounded (OOM guard)"
    assert 0 < queue.max_jobs < 100_000, "the job store must be bounded (memory-leak guard)"
    assert queue.job_ttl > 0, "finished jobs must expire"


def test_the_hard_timeout_exceeds_the_predict_deadline(ai_source, jobqueue_module):
    """The hard-timeout reaper abandons a job it presumes hung. If that deadline were <= the
    /predict wait (AI_PREDICT_TIMEOUT_SECONDS), the reaper would abandon jobs that a caller is
    still legitimately waiting on — turning every slow-but-healthy prediction into a failure."""
    queue = jobqueue_module.JobQueue(executor_factory=lambda: ThreadPoolExecutor(max_workers=1))
    assert queue.hard_timeout > _predict_timeout_default(ai_source)


def test_the_queue_defaults_to_at_least_one_worker(jobqueue_module):
    queue = jobqueue_module.JobQueue(executor_factory=lambda: ThreadPoolExecutor(max_workers=1))
    assert queue.workers >= 1


def test_the_default_pool_is_a_process_pool_not_a_thread_pool(jobqueue_module):
    """Threads cannot overlap CPU-bound scoring (the GIL). Swapping the pool to threads would look
    fine in every unit test — which inject a thread pool on purpose — and quietly forfeit the +5."""
    queue = jobqueue_module.JobQueue(workers=1)
    executor = queue._executor_factory()
    try:
        assert isinstance(executor, ProcessPoolExecutor)
    finally:
        executor.shutdown(wait=False)


# --------------------------------------------------------------------------- the container wiring


def test_ai_runs_exactly_one_gunicorn_worker(dockerfile, prod):
    """The job store is in-memory and per-process: with 2 workers, `POST /jobs` and `GET /jobs/<id>`
    hit different stores and the read 404s about half the time."""
    for source, name in ((dockerfile, "ai/Dockerfile"), (prod, "docker-compose.prod.yml")):
        assert '"--workers", "1"' in source, f"{name} must run ai with exactly one gunicorn worker"
        assert '"--workers", "2"' not in source, f"{name} must not run a second ai worker"


def test_ai_serves_concurrent_requests_with_threads(dockerfile, prod):
    """One worker + one thread would serialize at the HTTP layer, before the queue ever sees the
    second request — the pool's parallelism would be unreachable."""
    for source, name in ((dockerfile, "ai/Dockerfile"), (prod, "docker-compose.prod.yml")):
        assert '"--threads"' in source, f"{name} must give the single ai worker a thread pool"


def _ai_gunicorn_timeout(text):
    """The --timeout on the gunicorn command that serves ai (app:create_app()), or None if absent."""
    text = text.replace("\\\n", " ")  # join Dockerfile CMD line-continuations into one logical line
    for line in text.splitlines():
        if "gunicorn" in line and "app:create_app()" in line:
            m = re.search(r"--timeout['\",\s]+(\d+)", line)
            return int(m.group(1)) if m else None
    return None


def _predict_timeout_default(ai_source):
    """The queue's own deadline — AI_PREDICT_TIMEOUT_SECONDS' default in ai/app.py."""
    m = re.search(r'AI_PREDICT_TIMEOUT_SECONDS["\'],\s*["\'](\d+)', ai_source)
    assert m, "ai/app.py no longer reads AI_PREDICT_TIMEOUT_SECONDS with a literal default"
    return int(m.group(1))


def test_ai_gunicorn_timeout_exceeds_the_queue_timeout(ai_source, dockerfile, prod):
    """`/predict` waits on the pool up to AI_PREDICT_TIMEOUT_SECONDS, then answers 504 (a clean,
    countable degrade). If gunicorn's worker timeout is <= that deadline, it SIGKILLs the worker
    mid-wait instead: web sees a dropped connection, the in-flight job dies with the process, and the
    504 path is unreachable. gunicorn's default is 30 — exactly the queue's default — so the ai
    command must set --timeout explicitly, above it.
    """
    deadline = _predict_timeout_default(ai_source)
    for source, name in ((dockerfile, "ai/Dockerfile"), (prod, "docker-compose.prod.yml")):
        t = _ai_gunicorn_timeout(source)
        assert t is not None, f"{name}: the ai gunicorn command must set --timeout (default 30 races the queue)"
        assert t > deadline, f"{name}: gunicorn --timeout {t} must exceed the queue's {deadline}s deadline"


def test_ai_never_publishes_a_host_port(dev, prod):
    """The queue adds routes (`/jobs`, `/queue/stats`) that must stay internal: they take work with
    no auth. Only `web` is user-facing."""
    ai_dev = dev.split("  ai:", 1)[1].split("\n  db:", 1)[0]
    ai_prod = prod.split("  ai:", 1)[1].split("\n  db:", 1)[0]
    for block, name in ((ai_dev, "docker-compose.yml"), (ai_prod, "docker-compose.prod.yml")):
        assert "ports:" not in block, f"{name}: ai must expose, never publish"
        assert "expose:" in block


def test_the_prod_queue_pins_its_sizing_explicitly(prod):
    """Each pool process holds its own copy of the model, so pool size is a deliberate, VM-specific
    choice (4 = the E4ads v5's vCPUs). Prod must pin it rather than inherit the dev default — the
    container's core count is not the VM's, and an inherited default silently mis-sizes both knobs."""
    ai_prod = prod.split("  ai:", 1)[1].split("\n  db:", 1)[0]
    assert "AI_QUEUE_WORKERS" in ai_prod
    assert "AI_QUEUE_MAX_PENDING" in ai_prod


def test_ai_app_is_importable_by_file_path_not_only_from_its_workdir():
    """`test_skeleton_contract.py` (shared) execs ai/app.py by path, where `import jobqueue` does not
    resolve on its own. app.py puts its own directory on sys.path for exactly that reason — dropping
    that line breaks a teammate's suite, not ours, which is the worst way to find out."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("ai_app_path_loaded", str(ROOT / "ai" / "app.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # must not raise ModuleNotFoundError: jobqueue
    assert callable(module.create_app)


def test_the_test_runner_can_reach_the_ai_container(dev):
    """The live-queue system suite skips without AI_BASE_URL; without this wiring it would silently
    never run in CI."""
    test_stack = _strip_comments((ROOT / "docker-compose.test.yml").read_text())
    assert "AI_BASE_URL: http://ai:5000" in test_stack
    assert "ai: { condition: service_healthy }" in test_stack


# --------------------------------------------------------------- a worker that really dies (#555)

_DYING_TARGET = '''
import os
def suicide(features):
    os._exit(1)          # a segfaulting model / an OOM-killed worker, reproduced exactly
def fine(features):
    return {"state": "Ready", "proba": {"Ready": 1.0}, "recommendations": []}
'''


@pytest.fixture
def dying_target(tmp_path, monkeypatch):
    """Put an importable module on `sys.path` whose worker kills its own process.

    A real `ProcessPoolExecutor` child must be able to import the target by name, and the child
    inherits the parent's `sys.path` under both fork and spawn — so a tmp module works on Linux CI
    and on a Windows dev box alike.
    """
    (tmp_path / "wsnh_dying_worker.py").write_text(_DYING_TARGET, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    # `ai/` too: on a spawn platform the child re-imports `jobqueue` to unpickle `_worker`, and the
    # conftest loader drops that path once the module is in memory. Without this the child dies of
    # ModuleNotFoundError — still a BrokenProcessPool, but not the crash this test means to stage.
    monkeypatch.syspath_prepend(str(ROOT / "ai"))
    return "wsnh_dying_worker"


def test_a_worker_that_dies_does_not_wedge_the_queue(jobqueue_module, dying_target, monkeypatch):
    """A dead worker must cost one prediction, not the container.

    Reproduced on a live `ai` container before this guard existed: killing one pool worker left
    `/queue/stats` and `/jobs` hanging FOREVER while `/health` still answered 200, so Docker kept
    reporting the container healthy and never restarted it — every prediction 504'd behind a lock
    nobody would ever release. The cause is that a process pool runs its done-callbacks on its own
    executor-manager thread, so rebuilding that pool from inside the callback deadlocks; every test
    that only SIMULATES `BrokenProcessPool` (from a fake executor, or a ThreadPoolExecutor whose
    callbacks run on ordinary threads) is blind to it. Hence a real process, really dying.
    """
    monkeypatch.setenv("AI_WORKER_TARGET", f"{dying_target}:suicide")
    # Real process pool via SPAWN (#605): this test's whole point is a worker that really dies, so it
    # cannot use a thread pool -- and a forked pool here is exactly what leaks to interpreter exit when
    # its bounded teardown (closer.join(15) below) times out. The fixture already prepends `ai/` so the
    # spawned child re-imports the target.
    queue = jobqueue_module.JobQueue(workers=1, max_pending=8, executor_factory=_spawn_pool(1))
    queue.start()
    try:
        job_id = queue.submit({"sleep_hours": 8})
        with pytest.raises(Exception) as raised:
            queue.result(job_id, timeout=30)
        # The caller learns the job died; it must NOT be told "you waited too long" — that reads as a
        # slow model and invites a retry into the same broken pool.
        assert "BrokenProcessPool" in type(raised.value).__name__ or "BrokenProcessPool" in str(raised.value), \
            f"a crashed worker must surface as a crash, got {type(raised.value).__name__}: {raised.value}"

        # The queue is still answering: this is the assertion that was impossible before the fix.
        answered = []
        probe = threading.Thread(target=lambda: answered.append(queue.stats()), daemon=True)
        probe.start()
        probe.join(20)
        assert answered, "stats() never returned — the queue lock is held by the crash handler"
        assert answered[0]["failed"] >= 1

        # ...and it can still do work: the pool was replaced rather than left broken.
        monkeypatch.setenv("AI_WORKER_TARGET", f"{dying_target}:fine")
        queue.target = f"{dying_target}:fine"
        recovered = queue.submit({"sleep_hours": 8})
        assert queue.result(recovered, timeout=30)["state"] == "Ready"
        assert queue.stats()["pool_rebuilds"] >= 1
    finally:
        # Even the teardown has to survive the bug: with the lock held, `shutdown()` never returns,
        # and a hanging teardown would take the whole suite down with it rather than report a failure.
        closer = threading.Thread(target=queue.shutdown, daemon=True)
        closer.start()
        closer.join(15)
