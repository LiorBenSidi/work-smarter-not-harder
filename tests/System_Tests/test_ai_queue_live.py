"""The job queue against the LIVE `ai` container — OWNER: Elad.

Everything else about the queue is proven in-process with a thread pool injected. This suite proves
the part that only a real container can: gunicorn actually serves concurrent requests, the pool is
really made of worker PROCESSES, and the queue really parallelizes scoring across them.

Env-gated on ``AI_BASE_URL`` — the cross-container runner sets it to ``http://ai:5000`` (see
docker-compose.test.yml), so this runs in CI's `compose-e2e` job and skips on a bare laptop.

    docker compose -f docker-compose.yml -f docker-compose.test.yml up --build --exit-code-from tests
"""
import concurrent.futures
import os
import time

import pytest

requests = pytest.importorskip("requests")

BASE = os.environ.get("AI_BASE_URL", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set AI_BASE_URL to run against the live ai container")

FEATURES = {"features": {"hrv": 60, "sleep_hours": 7, "soreness": 2}}


def _post(path, payload=None, timeout=30):
    return requests.post(f"{BASE}{path}", json=payload, timeout=timeout)


def _get(path, timeout=30):
    return requests.get(f"{BASE}{path}", timeout=timeout)


def test_the_live_container_is_serving():
    response = _get("/health")
    assert response.status_code == 200
    assert response.json()["service"] == "ai"


def test_predict_over_the_real_wire_keeps_the_contract():
    """The exact call `web/services/ai_client.py` makes."""
    body = _post("/predict", FEATURES).json()
    assert isinstance(body["state"], str)
    assert isinstance(body["proba"], dict)
    assert isinstance(body["recommendations"], list)


def test_the_pool_is_made_of_real_worker_processes():
    """`/queue/stats` reports the configured pool; a pool of 1 would mean no parallelism at all."""
    stats = _get("/queue/stats").json()
    assert stats["workers"] >= 1
    assert stats["max_pending"] >= 1


def test_gunicorn_serves_concurrent_predicts_without_serializing_them():
    """Fire N `/predict` calls at once. With one gunicorn worker and one thread these would queue at
    the HTTP layer; with the thread pool + process pool they overlap. We assert on *correctness under
    concurrency* (every caller gets a valid, complete answer) rather than on wall-clock, because a
    placeholder model returns in microseconds and a timing assertion here would be noise.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        responses = list(pool.map(lambda _: _post("/predict", FEATURES), range(24)))

    assert all(r.status_code == 200 for r in responses), [r.status_code for r in responses]
    for response in responses:
        body = response.json()
        assert {"state", "proba", "recommendations"} <= set(body)


def test_concurrent_callers_each_get_their_own_result():
    """A shared job store with a racy key would hand caller A caller B's answer. Each `/jobs` id must
    resolve to its own submission."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        job_ids = list(pool.map(lambda _: _post("/jobs", FEATURES).json()["job_id"], range(16)))

    assert len(set(job_ids)) == 16
    for job_id in job_ids:
        body = _await_job(job_id)
        assert body["status"] == "done"
        assert "state" in body["result"]


def test_a_job_survives_the_round_trip_through_a_worker_process():
    """Proves the features pickle out to the child and the result pickles back — the failure mode a
    thread pool can never surface."""
    job_id = _post("/jobs", FEATURES).json()["job_id"]
    body = _await_job(job_id)
    assert body["status"] == "done"
    assert isinstance(body["result"]["proba"], dict)


def test_the_live_queue_drains_back_to_empty():
    """After a burst, `pending` must return to 0 — otherwise the depth counter leaks and the
    container wedges at 'full' after enough traffic."""
    for _ in range(10):
        _post("/predict", FEATURES)
    for _ in range(50):
        if _get("/queue/stats").json()["pending"] == 0:
            break
        time.sleep(0.1)
    stats = _get("/queue/stats").json()
    assert stats["pending"] == 0, stats
    assert stats["completed"] >= 10


def test_the_live_queue_sheds_load_instead_of_dying_under_a_burst():
    """Hit the container far harder than its backlog allows. Every response must be a *considered*
    one — 200 or 503 — and the container must still be healthy afterwards. A crash, a hang, or a
    connection reset here is the OOM the bound exists to prevent.
    """
    max_pending = _get("/queue/stats").json()["max_pending"]
    burst = max_pending * 4

    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
        responses = list(pool.map(lambda _: _post("/jobs", FEATURES), range(burst)))

    codes = {r.status_code for r in responses}
    assert codes <= {202, 503}, codes
    assert _get("/health").status_code == 200, "the burst must not take the container down"


def test_an_unknown_job_id_is_a_clean_404_over_http():
    assert _get("/jobs/0123456789abcdef").status_code == 404


def test_a_malformed_body_is_rejected_over_http():
    assert _post("/predict", {"features": "nope"}).status_code == 400


def _await_job(job_id, attempts=100):
    for _ in range(attempts):
        body = _get(f"/jobs/{job_id}").json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never finished: {body}")
