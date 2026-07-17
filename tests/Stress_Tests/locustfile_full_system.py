"""Whole-system locust scenario — EVERY committed feature under one mixed load. OWNER: Elad.

`locustfile.py` (next to this file) stresses the single-IP ABUSE surface: one attacker, the rate-limit
fences engaging. This file answers the other stress question — **feature capacity**: how many *distinct,
well-behaved* users can use the whole site at once, and what degrades first. Findings + staged numbers:
docs/STRESS_REPORT.md.

Every simulated user runs the real signup flow (register -> emailed code -> /register/verify; mock email
mode surfaces the code as ``dev_code``), then mixes reads (dashboard, history, forum, DMs, notification
polling, engagement) with writes (check-in -> the ai queue, posts, comments, votes, DMs, media
upload/serve) in roughly the ratios a real session would.

DISTINCT IPs: each user stamps a random ``X-Forwarded-For``. web trusts exactly one proxy hop
(ProxyFix ``x_for=1`` — in this direct-to-web run locust IS that hop), so flask-limiter keys each
simulated user separately, exactly like real visitors behind Caddy. Per-user task rates sit under every
per-IP cap, so a 429 here is a real finding (a cap throttling normal use), not the abuse fence working.

Response classification (drives the what-falls/what-holds report):
    2xx / expected 4xx   -> pass
    429                  -> failure tagged FENCE  (a rate limit throttled NORMAL use)
    503                  -> failure tagged SHED   (backpressure/unavailable — the defence, tracked)
    507                  -> failure tagged CAP    (the media disk cap engaged — the defence, tracked)
    other 5xx / drop     -> failure tagged SERVER-ERROR (a real fall-over)

Run (on demand, needs a live stack — never a per-PR gate):

    docker compose up --build -d
    locust -f tests/Stress_Tests/locustfile_full_system.py --headless -u 100 -r 10 -t 2m \
           --host http://localhost:8000 --csv full_system

Stage it (20 -> 50 -> 100 -> 200 -> 300 users) to find the knee; see docs/STRESS_REPORT.md for the
2026-07-16 baseline (clean through 100 users; saturation knee between 100 and 200 on 2 gunicorn workers).
"""
import io
import os
import random
import uuid

from locust import HttpUser, between, task

PNG = b"\x89PNG\r\n\x1a\n" + b"stress-pixel" * 8   # tiny blob; the route validates mimetype, not magic
HUB = os.environ.get("LOCUST_HUB", "stress_hub")    # shared DM recipient — register it once first (or DMs 404, tracked as pass)


def classify(r, allowed=()):
    """success/failure per the module contract above; keeps every task's pass/fail bar identical."""
    if r.status_code < 400 or r.status_code in allowed:
        r.success()
    elif r.status_code == 429:
        r.failure("FENCE-429 (rate limit hit by NORMAL use)")
    elif r.status_code == 503:
        r.failure("SHED-503 (backpressure engaged)")
    elif r.status_code == 507:
        r.failure("CAP-507 (media disk cap engaged)")
    else:
        r.failure(f"SERVER-ERROR-{r.status_code}")


class FullSiteUser(HttpUser):
    """One well-behaved visitor exercising every feature; task weights ~ a real session's mix."""

    wait_time = between(0.5, 2.0)

    def _h(self):
        return {"X-CSRF-Token": self.client.cookies.get("csrf_token", "")}

    def on_start(self):
        # A distinct client IP per user -> per-IP limits act per-user (collision odds negligible).
        self.client.headers["X-Forwarded-For"] = (
            f"10.{random.randint(1, 254)}.{random.randint(1, 254)}.{random.randint(1, 254)}")  # noqa: S311
        self.ok = False          # tasks no-op until signup lands, so a dropped signup can't cascade 401s
        self.post_id = None
        self.media_id = None
        self.client.get("/health", name="[setup] csrf seed")
        user = "st_" + uuid.uuid4().hex[:10]
        creds = {"username": user, "password": "s3cretpw!", "email": user + "@ex.com"}
        # The REAL 2-step signup (verify_email defaults ON): mock email mode returns the code as
        # dev_code; /register/verify creates the account and signs the session straight in.
        r = self.client.post("/register", json=creds, headers=self._h(), name="[setup] /register")
        try:
            code = r.json().get("dev_code", "")
        except ValueError:
            return                                       # dropped mid-ramp -> stay idle, don't 401-spam
        v = self.client.post("/register/verify", json={"code": code}, headers=self._h(),
                             name="[setup] /register/verify")
        if v.status_code != 201:
            return
        self.ok = True
        self.client.get("/health", name="[setup] csrf reseed")   # verify clears the session -> new token
        self.client.post("/profile", json={"age": 25, "gender": "other", "height": 175.0,
                                           "weight": 72.5, "goal": "maintain", "training_frequency": 4},
                         headers=self._h(), name="[setup] /profile")
        r = self.client.post("/forum/posts", json={"title": f"stress {user}", "body": "campaign post"},
                             headers=self._h(), name="[setup] post")   # own comment/vote target (1 < 10/min cap)
        try:
            self.post_id = r.json()["post"]["id"]
        except (ValueError, KeyError):
            self.post_id = None

    # ---- read paths (un-fenced: must hold raw) ------------------------------------------------
    @task(6)
    def notifications_poll(self):
        if not self.ok:
            return
        with self.client.get("/notifications", catch_response=True) as r:
            classify(r)

    @task(5)
    def dashboard(self):
        if not self.ok:
            return
        with self.client.get("/dashboard", catch_response=True) as r:
            classify(r)

    @task(4)
    def forum_list(self):
        if not self.ok:
            return
        with self.client.get("/forum/posts", catch_response=True) as r:
            classify(r)

    @task(3)
    def history(self):
        if not self.ok:
            return
        with self.client.get("/history", catch_response=True) as r:
            classify(r)

    @task(3)
    def forum_read(self):
        if not (self.ok and self.post_id):
            return
        with self.client.get(f"/forum/posts/{self.post_id}", name="/forum/posts/[id]",
                             catch_response=True) as r:
            classify(r)

    @task(2)
    def conversations(self):
        if not self.ok:
            return
        with self.client.get("/conversations", catch_response=True) as r:
            classify(r)

    @task(1)
    def engagement(self):
        if not self.ok:
            return
        with self.client.get("/me/engagement", catch_response=True) as r:
            classify(r)

    # ---- write paths (per-IP fenced; this scenario stays under every cap) ----------------------
    @task(2)
    def checkin_to_ai(self):
        # web -> ai job queue -> model: THE cross-container hot path (a 503 = the queue shedding).
        if not self.ok:
            return
        with self.client.post("/checkin",
                              json={"sleep_hours": round(random.uniform(4, 9), 1),   # noqa: S311
                                    "resting_hr": 55,
                                    "fatigue": random.randint(1, 5),                 # noqa: S311
                                    "soreness": random.randint(1, 5),                # noqa: S311
                                    "training_load": random.randint(1, 10)},         # noqa: S311
                              headers=self._h(), catch_response=True) as r:
            classify(r)

    @task(2)
    def dm_send(self):
        if not self.ok:
            return
        with self.client.post("/messages", json={"to": HUB, "body": "stress hello"},
                              headers=self._h(), catch_response=True) as r:
            classify(r, allowed=(404,))   # hub not seeded = setup gap, not a fall-over

    @task(2)
    def vote(self):
        if not (self.ok and self.post_id):
            return
        with self.client.post(f"/forum/posts/{self.post_id}/vote",
                              json={"value": random.choice((1, -1))},                # noqa: S311
                              headers=self._h(), name="/forum/posts/[id]/vote", catch_response=True) as r:
            classify(r, allowed=(400,))   # a rejected self-vote is a rule, not a fall-over

    @task(1)
    def comment(self):
        if not (self.ok and self.post_id):
            return
        with self.client.post(f"/forum/posts/{self.post_id}/comments", json={"body": "stress comment"},
                              headers=self._h(), name="/forum/posts/[id]/comments", catch_response=True) as r:
            classify(r)

    @task(1)
    def media_upload(self):
        if not self.ok:
            return
        with self.client.post("/media", files={"file": ("p.png", io.BytesIO(PNG), "image/png")},
                              headers=self._h(), catch_response=True) as r:
            classify(r)
            if r.status_code < 300:
                try:
                    self.media_id = r.json()["id"]
                except (ValueError, KeyError):
                    pass

    @task(2)
    def media_serve(self):
        if not (self.ok and self.media_id):
            return
        with self.client.get(f"/media/{self.media_id}", name="/media/[id]", catch_response=True) as r:
            classify(r)
