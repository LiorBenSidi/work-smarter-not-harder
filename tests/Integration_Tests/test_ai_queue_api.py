"""The `ai` container's HTTP surface, wired to a real JobQueue — OWNER: Elad.

These drive `ai/app.py` through Flask's test client with a thread-pool-backed queue injected, so the
routes, the queue, and the model seam are exercised together without spawning processes.

The single most important assertion in this file is that `POST /predict` still answers with
`state` + `proba` + `recommendations`: that is the `web -> ai` contract, and putting a queue in front
of the model must be invisible to `web`.
"""
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

# A body the readiness validator accepts: all four required fields, each in range (ai/app.py). Merge
# extra keys onto it when a test needs the request to pass validation and actually reach the queue.
VALID = {"sleep_hours": 8, "fatigue": 2, "soreness": 1, "training_load": 100}


def echo(features):
    return {"state": "High", "proba": {"High": 0.9, "Low": 0.1}, "recommendations": ["rest"]}


def boom(features):
    raise RuntimeError("model exploded")


def slow(features):
    time.sleep(features.get("seconds", 0.3))
    return {"state": "Moderate", "proba": {"Moderate": 1.0}, "recommendations": []}


@pytest.fixture
def make_client(ai_app_module, jobqueue_module, monkeypatch):
    created = []

    def _make(target=echo, *, workers=4, max_pending=64, predict_timeout="30"):
        monkeypatch.setenv("AI_PREDICT_TIMEOUT_SECONDS", predict_timeout)
        monkeypatch.setattr(jobqueue_module, "_resolve_target", lambda _name: target)
        queue = jobqueue_module.JobQueue(
            workers=workers,
            max_pending=max_pending,
            executor_factory=lambda: ThreadPoolExecutor(max_workers=workers),
        )
        created.append(queue)
        app = ai_app_module.create_app(queue=queue)
        app.config["TESTING"] = True
        return app.test_client()

    yield _make
    for queue in created:
        # wait=True: a pool still draining after teardown would resolve its worker target through
        # the NEXT test's monkeypatch, and quietly run that test's function. Cross-test leak.
        queue.shutdown(wait=True)


# --------------------------------------------------------------------------- the web->ai contract


def test_predict_still_returns_the_contract_shape(make_client):
    """`web` reads exactly these keys (web/services/ai_client.py). The queue must not change them."""
    response = make_client().post("/predict", json={"features": dict(VALID)})
    assert response.status_code == 200
    body = response.get_json()
    assert body["state"] == "High"
    assert body["proba"] == {"High": 0.9, "Low": 0.1}
    assert body["recommendations"] == ["rest"]


def test_predict_passes_the_features_through_to_the_model(make_client):
    seen = {}

    def capture(features):
        seen.update(features)
        return echo(features)

    payload = {**VALID, "hrv": 60}
    make_client(capture).post("/predict", json={"features": payload})
    assert seen == payload


def test_predict_rejects_an_empty_body_now_the_model_needs_the_four_fields(make_client):
    """The readiness model can't score without its four inputs, so `/predict` refuses an empty
    features map at the boundary (400) rather than letting a worker impute invented values.

    NOTE (web follow-up, Lior): web must now always send the four readiness fields. `dashboard.py`
    currently posts profile-only and will degrade to ai_status='unavailable' until it sends them.
    """
    response = make_client().post("/predict", json={"features": {}})
    assert response.status_code == 400
    assert "required" in response.get_json()["error"]


def test_health_is_unchanged(make_client):
    body = make_client().get("/health").get_json()
    assert body == {"status": "ok", "service": "ai"}


# --------------------------------------------------------------------------- degradation paths


def test_predict_sheds_load_with_503_when_the_queue_is_full(make_client):
    """`web`'s ai_client treats a non-200 as 'ai unavailable' and degrades — it must never see a
    crashed container instead.

    The backlog is filled through `/jobs` (which returns immediately) rather than `/predict`: a
    synchronous `/predict` from this single-threaded test client would block until its own slot
    freed, so it could never observe a full queue.
    """
    client = make_client(slow, workers=1, max_pending=2)
    for _ in range(2):
        assert client.post("/jobs", json={"features": {"seconds": 0.4}}).status_code == 202

    response = client.post("/predict", json={"features": {**VALID, "seconds": 0.4}})
    assert response.status_code == 503
    assert "queue full" in response.get_json()["error"]


def test_predict_returns_504_when_the_model_outruns_the_timeout(make_client):
    client = make_client(slow, predict_timeout="0.05")
    response = client.post("/predict", json={"features": {**VALID, "seconds": 0.5}})
    assert response.status_code == 504
    assert "timed out" in response.get_json()["error"]


def test_predict_returns_500_when_the_model_raises(make_client):
    response = make_client(boom).post("/predict", json={"features": dict(VALID)})
    assert response.status_code == 500
    assert response.get_json()["error"] == "prediction failed"


def test_a_model_crash_does_not_take_the_container_down(make_client):
    """One bad feature vector must not stop the next caller from being served."""
    targets = iter([boom, echo])
    client = make_client(lambda features: next(targets)(features))
    assert client.post("/predict", json={"features": dict(VALID)}).status_code == 500
    assert client.post("/predict", json={"features": dict(VALID)}).status_code == 200


def test_a_dead_worker_process_costs_one_503_not_a_500_forever(make_client):
    """A worker PROCESS dying (OOM/segfault) resolves its job's future to BrokenProcessPool. The
    caller whose job died gets a retryable 503 — their result is genuinely lost — and the queue
    rebuilds its pool, so the very next /predict is served normally. Before the self-heal this was
    a 500 on every request until someone restarted the container."""
    from concurrent.futures.process import BrokenProcessPool

    def worker_died(features):
        raise BrokenProcessPool("A child process terminated abruptly")

    targets = iter([worker_died, echo])
    client = make_client(lambda features: next(targets)(features))

    response = client.post("/predict", json={"features": dict(VALID)})
    assert response.status_code == 503
    assert "retry" in response.get_json()["error"]

    assert client.post("/predict", json={"features": dict(VALID)}).status_code == 200
    assert client.get("/queue/stats").get_json()["pool_rebuilds"] == 1


# --------------------------------------------------------------------------- the async job API


def test_jobs_accepts_and_returns_a_queued_id(make_client):
    response = make_client().post("/jobs", json={"features": {"hrv": 60}})
    assert response.status_code == 202
    body = response.get_json()
    assert body["status"] == "queued"
    assert body["job_id"]


def test_a_submitted_job_can_be_read_back_when_it_finishes(make_client):
    client = make_client()
    job_id = client.post("/jobs", json={"features": {"hrv": 60}}).get_json()["job_id"]
    body = _poll(client, job_id)
    assert body["status"] == "done"
    assert body["result"]["state"] == "High"


def test_a_failed_job_reports_the_error_not_a_result(make_client):
    client = make_client(boom)
    job_id = client.post("/jobs", json={"features": {}}).get_json()["job_id"]
    body = _poll(client, job_id)
    assert body["status"] == "failed"
    assert "model exploded" in body["error"]
    assert "result" not in body


def test_an_unknown_job_id_is_a_404_not_a_500(make_client):
    response = make_client().get("/jobs/deadbeef")
    assert response.status_code == 404
    assert response.get_json()["error"] == "unknown job"


def test_jobs_sheds_load_with_503_when_full(make_client):
    client = make_client(slow, workers=1, max_pending=1)
    client.post("/jobs", json={"features": {"seconds": 0.4}})
    codes = [client.post("/jobs", json={"features": {"seconds": 0.4}}).status_code for _ in range(3)]
    assert 503 in codes


# --------------------------------------------------------------------------- stats


def test_queue_stats_reports_depth_and_bound(make_client):
    client = make_client()
    client.post("/predict", json={"features": dict(VALID)})
    stats = client.get("/queue/stats").get_json()
    assert stats["max_pending"] == 64
    assert stats["workers"] == 4
    assert stats["submitted"] == 1
    assert stats["completed"] == 1
    assert stats["pending"] == 0


# --------------------------------------------------------------------------- input validation


@pytest.mark.parametrize("route", ["/predict", "/jobs"])
@pytest.mark.parametrize(
    "body",
    [
        {"features": "not-an-object"},
        {"features": ["a", "b"]},
        {"features": 42},
    ],
)
def test_a_non_object_features_field_is_rejected_before_a_worker_is_spent(make_client, route, body):
    response = make_client().post(route, json=body)
    assert response.status_code == 400


@pytest.mark.parametrize("route", ["/predict", "/jobs"])
def test_a_non_object_body_is_rejected(make_client, route):
    assert make_client().post(route, json=["not", "a", "dict"]).status_code == 400


def test_a_rejected_request_never_reached_a_worker(make_client):
    calls = []

    def counting(features):
        calls.append(features)
        return echo(features)

    client = make_client(counting)
    client.post("/predict", json={"features": "nope"})
    assert calls == []
    assert client.get("/queue/stats").get_json()["submitted"] == 0


# --------------------------------------------------------------------------- readiness-field validation


@pytest.mark.parametrize(
    "bad,reason",
    [
        ({}, "sleep_hours is required"),
        ({"sleep_hours": 8, "fatigue": 2, "soreness": 1}, "training_load is required"),
        ({**VALID, "fatigue": 11}, "fatigue must be between 1 and 10"),
        ({**VALID, "sleep_hours": 0}, "sleep_hours must be between 1 and 24"),
        ({**VALID, "soreness": "sore"}, "soreness must be a number"),
        ({**VALID, "training_load": True}, "training_load must be a number"),
    ],
)
def test_predict_rejects_an_unscoreable_readiness_request_before_a_worker(make_client, bad, reason):
    """A missing, non-numeric, or out-of-range readiness field must 400 at the boundary and never
    reach a worker — the model would otherwise score partly-invented input (Shiri's contract). The
    error names the offending field so `web` (and a human) can act on it."""
    calls = []

    def counting(features):
        calls.append(features)
        return echo(features)

    client = make_client(counting)
    response = client.post("/predict", json={"features": bad})
    assert response.status_code == 400
    assert reason in response.get_json()["error"]
    assert calls == []
    assert client.get("/queue/stats").get_json()["submitted"] == 0


def test_predict_accepts_a_complete_in_range_readiness_request(make_client):
    """The mirror of the rejection cases: the four fields present and in range go through to the
    model and come back with the contract shape."""
    response = make_client().post("/predict", json={"features": dict(VALID)})
    assert response.status_code == 200
    assert {"state", "proba", "recommendations"} <= set(response.get_json())


# --------------------------------------------------------------------------- helper


def _poll(client, job_id, attempts=100):
    for _ in range(attempts):
        body = client.get(f"/jobs/{job_id}").get_json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished: {body}")
