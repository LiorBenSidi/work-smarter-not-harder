"""Security posture of the job-queue routes — OWNER: Elad.

`ai` is internal: it has no auth layer, because nothing but `web` can reach it (only `web` publishes a
host port — locked by `test_ai_queue_contract.py` and `test_deploy_contract.py`). That makes two
things load-bearing:

  * **job ids must be unguessable.** They are the only handle on a result. A sequential id would let
    anything that got onto the compose network read other users' readiness scores by counting.
  * **a hostile body must never reach a worker process.** Validation happens before `submit()`, so a
    malicious payload costs a 400 rather than a pickled round-trip into a child process.
"""
import time
from concurrent.futures import ThreadPoolExecutor

import pytest


def echo(features):
    return {"state": "High", "proba": {"High": 1.0}, "recommendations": [], "echo": features}


@pytest.fixture
def client(ai_app_module, jobqueue_module, monkeypatch):
    monkeypatch.setattr(jobqueue_module, "_resolve_target", lambda _name: echo)
    queue = jobqueue_module.JobQueue(
        workers=2, executor_factory=lambda: ThreadPoolExecutor(max_workers=2)
    )
    app = ai_app_module.create_app(queue=queue)
    app.config["TESTING"] = True
    yield app.test_client()
    queue.shutdown(wait=False)


# --------------------------------------------------------------------------- job ids


def test_job_ids_are_not_sequential_or_guessable(client):
    ids = [client.post("/jobs", json={"features": {}}).get_json()["job_id"] for _ in range(10)]
    assert len(set(ids)) == 10
    assert all(len(job_id) == 32 for job_id in ids), "expected uuid4 hex"
    assert all(int(job_id, 16) for job_id in ids), "ids must be hex, not counters"
    # No two ids may share a common prefix long enough to enumerate from.
    assert len({job_id[:8] for job_id in ids}) == 10


@pytest.mark.parametrize("guess", ["1", "0" * 32, "a" * 32, "deadbeef", "-1"])
def test_a_guessed_job_id_reveals_nothing(client, guess):
    """404 with a flat error body — not a 500, not a stack trace, not another caller's result."""
    response = client.get(f"/jobs/{guess}")
    assert response.status_code == 404, guess
    assert response.get_json() == {"error": "unknown job"}


@pytest.mark.parametrize("hostile", ["../../etc/passwd", "%2e%2e%2f", "a/../../b", "..%2f..%2fetc"])
def test_a_traversal_shaped_job_id_never_reaches_the_handler(client, hostile):
    """Werkzeug normalizes/rejects these before routing, so they can never be read as a job id. The
    assertion is that they stay 4xx and leak nothing — the body here is Werkzeug's, not ours."""
    response = client.get(f"/jobs/{hostile}")
    assert response.status_code in (400, 404, 308), hostile
    assert "etc/passwd" not in response.get_data(as_text=True)


def test_one_callers_job_id_does_not_expose_anothers_result(client):
    first = client.post("/jobs", json={"features": {"owner": "a"}}).get_json()["job_id"]
    second = client.post("/jobs", json={"features": {"owner": "b"}}).get_json()["job_id"]
    assert first != second
    assert _poll(client, first)["result"]["echo"] == {"owner": "a"}
    assert _poll(client, second)["result"]["echo"] == {"owner": "b"}


# --------------------------------------------------------------------------- hostile input


@pytest.mark.parametrize(
    "features",
    [
        {"$where": "sleep(1000)"},          # NoSQL-injection-shaped key
        {"__class__": "gotcha"},            # attribute-traversal-shaped key
        {"a" * 5000: 1},                    # absurd key
        {"hrv": {"$gt": ""}},               # operator object as a value
        {"hrv": "'; DROP TABLE users; --"},
    ],
)
def test_hostile_feature_content_is_handled_not_executed(client, features):
    """The model seam receives data, never code. These must not 500 — the queue passes them through
    to a worker that treats them as opaque values (and the worker is a separate process anyway)."""
    response = client.post("/predict", json={"features": features})
    assert response.status_code == 200
    assert response.get_json()["state"] == "High"


@pytest.mark.parametrize("route", ["/predict", "/jobs"])
def test_an_oversized_body_is_refused(client, route):
    """MAX_CONTENT_LENGTH stops a multi-megabyte body before Flask parses it into memory."""
    payload = b'{"features": {"x": "' + b"a" * (128 * 1024) + b'"}}'
    response = client.post(route, data=payload, content_type="application/json")
    assert response.status_code == 413


@pytest.mark.parametrize("route", ["/predict", "/jobs"])
def test_a_feature_bomb_is_refused_before_it_costs_a_worker(client, route):
    """Many small keys stay under MAX_CONTENT_LENGTH but still blow up a per-feature model loop."""
    response = client.post(route, json={"features": {f"f{n}": n for n in range(1000)}})
    assert response.status_code == 400


@pytest.mark.parametrize("route", ["/predict", "/jobs"])
def test_a_body_that_is_not_json_is_refused(client, route):
    response = client.post(route, data="not json at all", content_type="text/plain")
    assert response.status_code == 400


def test_an_error_response_does_not_leak_internals(client, ai_app_module, jobqueue_module):
    """A model traceback must not reach the caller through `/predict` — `web` would render it."""

    def boom(features):
        raise RuntimeError("/secret/model/path.pkl is missing")

    queue = jobqueue_module.JobQueue(
        workers=1, executor_factory=lambda: ThreadPoolExecutor(max_workers=1)
    )
    jobqueue_module._resolve_target = lambda _name: boom
    app = ai_app_module.create_app(queue=queue)
    app.config["TESTING"] = True
    try:
        response = app.test_client().post("/predict", json={"features": {}})
        assert response.status_code == 500
        assert response.get_json() == {"error": "prediction failed"}
        assert "secret" not in response.get_data(as_text=True)
    finally:
        queue.shutdown(wait=False)


# --------------------------------------------------------------------------- exposure


def test_queue_stats_does_not_expose_job_payloads(client):
    """`/queue/stats` is an operator view. It must report depth, never the features or results that
    passed through — those are user health data."""
    client.post("/predict", json={"features": {"resting_hr": 48}})
    stats = client.get("/queue/stats").get_json()
    assert "48" not in str(stats)
    assert set(stats) == {
        "workers",
        "pending",
        "max_pending",
        "tracked_jobs",
        "submitted",
        "completed",
        "failed",
        "rejected",
    }


def _poll(client, job_id, attempts=100):
    for _ in range(attempts):
        body = client.get(f"/jobs/{job_id}").get_json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished: {body}")
