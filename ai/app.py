"""AI decision engine (internal container). OWNER: Shiri (model) · Elad (the queue in front of it).

CONTRACT (don't change without updating docs/DESIGN.md + telling the team):
    POST /predict  {features: {...}} -> {state: <category>, proba: {...}, recommendations: [...]}

The model itself lives in `inference.predict_one` (Shiri's seam — the trained model is baked into the
image, see Dockerfile). This module only routes: every scoring request goes through `jobqueue.JobQueue`,
which works the backlog on a pool of worker processes so concurrent callers are scored in parallel
rather than one after another (GUIDELINES.md §2). `/predict` keeps its synchronous request/response
shape; `/jobs` is the additive fire-and-forget path.

PMData notes + the open model decisions live in ai/README.md.
"""
import logging
import os
import sys
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path

from flask import Flask, jsonify, request

# The container runs with WORKDIR /app, so `import jobqueue` resolves. Tests (and the skeleton-contract
# suite) exec this file BY PATH, where it would not — put our own directory on sys.path so both work.
# The worker processes inherit this sys.path, which is also how they resolve `inference`.
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from jobqueue import JobNotFound, JobQueue, QueueFull  # noqa: E402  (needs the sys.path line above)

logger = logging.getLogger(__name__)

MAX_FEATURES = 200
MAX_CONTENT_LENGTH = 64 * 1024


def _features_or_error():
    """Validate the request body before it costs a worker process. Returns (features, error)."""
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None, "body must be a JSON object"
    features = body.get("features", {})
    if not isinstance(features, dict):
        return None, "features must be an object"
    if len(features) > MAX_FEATURES:
        return None, f"too many features (max {MAX_FEATURES})"
    return features, None


def create_app(queue=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LENGTH
    predict_timeout = float(os.environ.get("AI_PREDICT_TIMEOUT_SECONDS", "30"))

    queue = (queue or JobQueue()).start()
    app.config["JOB_QUEUE"] = queue

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="ai")

    @app.get("/queue/stats")
    def queue_stats():
        return jsonify(**queue.stats())

    @app.post("/predict")
    def predict():
        features, error = _features_or_error()
        if error:
            return jsonify(error=error), 400
        try:
            job_id = queue.submit(features)
        except QueueFull:
            # Shed load: a 503 keeps `ai` alive and lets `web` degrade gracefully. Growing the
            # backlog instead would OOM the container and take every in-flight request with it.
            logger.warning("shedding /predict: queue full (%d pending)", queue.stats()["pending"])
            return jsonify(error="queue full, retry shortly"), 503
        try:
            result = queue.result(job_id, timeout=predict_timeout)
        except FutureTimeout:
            logger.warning("job %s exceeded %.1fs", job_id, predict_timeout)
            return jsonify(error="prediction timed out"), 504
        except Exception:
            logger.exception("job %s raised in the worker", job_id)
            return jsonify(error="prediction failed"), 500
        return jsonify(**result)

    @app.post("/jobs")
    def enqueue_job():
        features, error = _features_or_error()
        if error:
            return jsonify(error=error), 400
        try:
            job_id = queue.submit(features)
        except QueueFull:
            return jsonify(error="queue full, retry shortly"), 503
        return jsonify(job_id=job_id, status="queued"), 202

    @app.get("/jobs/<job_id>")
    def read_job(job_id):
        try:
            job = queue.get(job_id)
        except JobNotFound:
            return jsonify(error="unknown job"), 404
        return jsonify(**job.as_dict())

    return app
