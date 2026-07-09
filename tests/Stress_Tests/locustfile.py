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
"""
import uuid

from locust import HttpUser, between, task

CSRF_COOKIE = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"


class WorkSmarterUser(HttpUser):
    """One simulated visitor: browses, polls readiness, and hammers the auth surface."""

    wait_time = between(0.5, 2.0)

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
