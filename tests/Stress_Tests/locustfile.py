"""Locust stress scenario against a RUNNING stack. OWNER: Elad.

Run it on demand (never as a per-commit merge gate — it needs a live stack and takes minutes):

    pip install locust
    docker compose up --build -d
    locust -f tests/Stress_Tests/locustfile.py --headless -u 50 -r 10 -t 1m \
           --host http://localhost:8000 --exit-code-on-error 1

WHAT WE DECIDED CAN CRASH, AND HOW IT IS DEFENDED (course: "decide in advance what can crash"):

* ``/login`` + ``/register`` — the brute-force / bulk-signup surface. Defence: ``flask-limiter``
  (20/min, 10/min). So **429 is a PASS here, not a failure** — it proves the defence engaged. Only a
  5xx (or a dropped connection) is a real failure: it means the app fell over instead of shedding load.
* ``/ready`` — pings Mongo on every call, so it is the first thing to buckle if the DB pool is
  exhausted. It must degrade to a clean 503, never a 500/timeout.
* ``/health`` — liveness; must stay 200 under any load, since Docker's healthcheck (and UptimeRobot)
  restart the container when it fails. A 429/5xx here would cause a restart storm under load, so
  ``/health`` is deliberately un-rate-limited and Mongo-independent.

Every task therefore marks 5xx as the failure and treats the rate-limit's 429 as the system
behaving correctly under abuse.

TWO USER CLASSES, picked with ``LOCUST_TARGET``:

* ``LOCUST_TARGET=web`` (default) — ``WorkSmarterUser`` above: the public abuse surface.
* ``LOCUST_TARGET=ai`` — ``AiPredictUser``: ramped load straight at the ``ai`` container's
  ``/predict``, which is the endpoint the job queue parallelizes. This is the **before/after** load
  (docs/SCALING_REPORT.md): run it once per pool size / replica count and compare RPS.

      # before
      AI_QUEUE_WORKERS=1 AI_WORKER_TARGET=bench:cpu_burn docker compose up -d --build
      LOCUST_TARGET=ai locust -f tests/Stress_Tests/locustfile.py --headless -u 8 -r 8 -t 30s \
             --host http://localhost:5099 --exit-code-on-error 1
      # after: AI_QUEUE_WORKERS=4, same command

  Against the placeholder model ``/predict`` returns in microseconds, so the measurement is only
  meaningful with the CPU-bound bench target (``AI_WORKER_TARGET=bench:cpu_burn``) — see ai/bench.py
  for why. ``scripts/scaling_benchmark.py`` is the same measurement without the locust dependency.
"""
import os
import uuid

from locust import HttpUser, between, constant, task

CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"

TARGET = os.environ.get("LOCUST_TARGET", "web").lower()


class AiPredictUser(HttpUser):
    """Saturates `ai`'s `/predict` — the endpoint the job queue parallelizes.

    No wait time: the point is to keep the queue full so throughput reflects the pool, not think-time.
    A 503 is the bounded queue shedding load correctly (a PASS); a 5xx other than 503, or a 504, means
    it fell over or wedged.
    """

    wait_time = constant(0)
    abstract = TARGET != "ai"  # only enabled with LOCUST_TARGET=ai

    @task
    def predict(self):
        with self.client.post(
            "/predict",
            json={"features": {"sleep_hours": 7, "resting_hr": 55, "fatigue": 3,
                               "soreness": 2, "training_load": 5}},
            catch_response=True,
        ) as r:
            if r.status_code == 200:
                r.success()
            elif r.status_code == 503:
                r.success()  # backpressure engaged — the defence, not a failure
            else:
                r.failure(f"expected 200 or 503, got {r.status_code}")


class WorkSmarterUser(HttpUser):
    """One simulated visitor: browses, polls readiness, and hammers the auth surface."""

    wait_time = between(0.5, 2.0)
    abstract = TARGET == "ai"  # disabled when the run targets the ai container directly

    def on_start(self):
        # Seed the double-submit CSRF cookie exactly like a browser does (one safe GET first).
        self.client.get("/health", name="/health [csrf seed]")

    def _csrf_headers(self):
        token = self.client.cookies.get(CSRF_COOKIE, "")
        return {CSRF_HEADER: token}

    def _check(self, response, allowed):
        """5xx (or no response) = the app fell over. Anything in `allowed` = it shed load correctly."""
        if response.status_code in allowed:
            response.success()
        else:
            response.failure(f"expected one of {sorted(allowed)}, got {response.status_code}")

    @task(5)
    def liveness(self):
        # Must ALWAYS be 200: Docker's healthcheck restarts the container on failure. A 429 here
        # would mean a load spike triggers a restart storm.
        with self.client.get("/health", catch_response=True) as r:
            self._check(r, {200})

    @task(3)
    def readiness(self):
        # Hits Mongo. Under pool exhaustion it must degrade to a clean 503, never a 500.
        with self.client.get("/ready", catch_response=True) as r:
            self._check(r, {200, 503})

    @task(3)
    def load_shell(self):
        with self.client.get("/", catch_response=True) as r:
            self._check(r, {200})

    @task(2)
    def brute_force_login(self):
        # Password guessing from one IP. 401 = rejected credentials, 429 = the rate-limit engaged.
        with self.client.post("/login", json={"username": "nobody", "password": "wrongpass"},
                              headers=self._csrf_headers(), catch_response=True) as r:
            self._check(r, {200, 400, 401, 429})

    @task(1)
    def bulk_register(self):
        # Bulk account creation from one IP: 200/201 for the first few, then 429 once the cap bites.
        user = "load_" + uuid.uuid4().hex[:10]
        with self.client.post("/register",
                              json={"username": user, "password": "s3cretpw!", "email": user + "@ex.com"},
                              headers=self._csrf_headers(), name="/register", catch_response=True) as r:
            self._check(r, {200, 201, 400, 409, 429})
