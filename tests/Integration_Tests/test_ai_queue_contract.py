"""Job-queue contract guards — OWNER: Elad.

The queue (GUIDELINES.md §2, +5) lives inside a container whose model code belongs to Shiri and whose
compose/prod wiring is shared. This file locks the handful of invariants that a well-meaning change
elsewhere can silently undo, so the breakage surfaces as a red CI run on the PR instead of as a dead
or OOM-killed `ai` container after a merge:

  * the `web -> ai` contract: `/predict` still answers `state` + `proba` + `recommendations`;
  * `/predict` still goes THROUGH the queue (not straight to the model — that re-serializes it and
    silently forfeits the +5);
  * the queue stays BOUNDED (an unbounded backlog is an OOM on the ~1 GB VM, not a slowdown);
  * the pool is a PROCESS pool (threads do not overlap CPU-bound inference — the GIL);
  * exactly ONE gunicorn worker serves `ai` (a second one owns a second in-memory job store, so
    `GET /jobs/<id>` would 404 whenever it landed on the wrong worker);
  * `inference.predict_one` still exists with the shape the pool expects. Shiri owns its BODY and may
    change it freely — these guards only pin its name and its return keys.
  * `ai` still publishes no host port, in dev and in prod.

Most are cheap text/introspection assertions (no Docker, no live stack), so they run in the normal
per-PR gate alongside `test_deploy_contract.py`.
"""
import inspect
import pickle
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path

import pytest

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
    """Shiri owns the VALUES; `web/services/ai_client.py` reads these KEYS."""
    result = inference_module.predict_one({"hrv": 60})
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
    result = inference_module.predict_one({"hrv": 60})
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


def test_ai_never_publishes_a_host_port(dev, prod):
    """The queue adds routes (`/jobs`, `/queue/stats`) that must stay internal: they take work with
    no auth. Only `web` is user-facing."""
    ai_dev = dev.split("  ai:", 1)[1].split("\n  db:", 1)[0]
    ai_prod = prod.split("  ai:", 1)[1].split("\n  db:", 1)[0]
    for block, name in ((ai_dev, "docker-compose.yml"), (ai_prod, "docker-compose.prod.yml")):
        assert "ports:" not in block, f"{name}: ai must expose, never publish"
        assert "expose:" in block


def test_the_prod_queue_is_sized_for_the_small_vm(prod):
    """Each pool process holds its own copy of the model; the course VM has ~1 GB. Prod must pin the
    pool size rather than inherit the dev default of one-per-core."""
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
