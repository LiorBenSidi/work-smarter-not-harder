"""MANDATORY stress test — OWNER: Elad.

Two layers, both driving a RUNNING stack (stress tests need real sockets, real gunicorn workers and a
real Mongo — an in-process Flask test client proves nothing about concurrency):

* this file — a fast, dependency-free concurrency burst (stdlib threads + ``requests``) that CI and the
  containerized test-runner can execute directly. Env-gated on ``E2E_BASE_URL``, so the normal
  no-stack CI run skips it cleanly instead of failing.
* ``locustfile.py`` (next to this file) — the full ramped locust scenario for the on-demand CI job and
  the before/after scaling numbers.

THE CONTRACT UNDER TEST — what we decided can crash, and how it is defended:
    /health   liveness, un-rate-limited, Mongo-independent -> must stay 200 under any burst, because
              Docker's healthcheck restarts the container when it fails (a 429/5xx = restart storm).
    /login    the brute-force surface -> flask-limiter sheds it. 429 is a PASS (the defence engaged);
              a 5xx is the failure (the app fell over instead of shedding).
    /forum/posts  the spam surface (GUIDELINES §3.6) -> flask-limiter sheds bulk posting from one IP.
              Same pass/fail bar as /login: 429 = the defence engaged, 5xx = the app fell over.
    /ready    pings Mongo -> must degrade to a clean 503 under DB pressure, never a 500 or a hang.
"""
import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

requests = pytest.importorskip("requests")

BASE = os.environ.get("E2E_BASE_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not BASE, reason="set E2E_BASE_URL to stress a live stack")

CONCURRENCY = 16
REQUESTS_PER_WORKER = 8
TIMEOUT = 10


def _csrf_session():
    s = requests.Session()
    s.get(f"{BASE}/health", timeout=TIMEOUT)   # seed the double-submit CSRF cookie
    return s


def _burst(call):
    """Run `call(i)` CONCURRENCY x REQUESTS_PER_WORKER times in parallel; return every status code.

    An exception (connection reset, timeout) is surfaced as the status code -1 so a dropped
    connection can never masquerade as a pass.
    """
    total = CONCURRENCY * REQUESTS_PER_WORKER

    def _one(i):
        try:
            return call(i)
        except requests.RequestException:
            return -1

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
        return list(pool.map(_one, range(total)))


def test_health_survives_a_concurrent_burst():
    """Liveness never sheds load: a burst must not make Docker's healthcheck fail (=> restart storm)."""
    session = requests.Session()
    codes = _burst(lambda _i: session.get(f"{BASE}/health", timeout=TIMEOUT).status_code)
    assert set(codes) == {200}, f"/health must stay 200 under load, saw {sorted(set(codes))}"


def test_login_flood_is_shed_with_429_never_5xx():
    """The brute-force surface sheds load via the rate-limit instead of crashing the worker."""
    session = _csrf_session()
    headers = {"X-CSRF-Token": session.cookies.get("csrf_token", "")}

    def _attempt(_i):
        return session.post(f"{BASE}/login", json={"username": "nobody", "password": "wrongpass"},
                            headers=headers, timeout=TIMEOUT).status_code

    codes = _burst(_attempt)
    assert -1 not in codes, "the server dropped a connection under load instead of answering"
    assert not [c for c in codes if c >= 500], f"login flood produced server errors: {sorted(set(codes))}"
    assert 429 in codes, f"the rate-limit never engaged under a {len(codes)}-request flood: {sorted(set(codes))}"


def test_forum_post_flood_is_shed_with_429_never_5xx():
    """The Forum's anti-spam cap (GUIDELINES §3.6): one IP bulk-creating posts is shed with 429.

    Auth-gated route, so the flood runs as a real registered user — which is exactly the abuse case:
    the rate-limit is what stands between one hijacked/spam account and a feed full of junk. The few
    posts that land before the limiter engages are deleted afterwards (author-only delete), so a run
    against a long-lived stack leaves nothing behind.
    """
    session = _csrf_session()
    headers = {"X-CSRF-Token": session.cookies.get("csrf_token", "")}
    user, pw = "stress_" + uuid.uuid4().hex[:8], "s3cret-stress-pw!"
    assert session.post(f"{BASE}/register",
                        json={"username": user, "password": pw, "email": user + "@example.com"},
                        headers=headers, timeout=TIMEOUT).status_code in (200, 201)
    assert session.post(f"{BASE}/login", json={"username": user, "password": pw},
                        headers=headers, timeout=TIMEOUT).status_code == 200

    created = []  # list.append is atomic, so worker threads may share it

    def _post(i):
        response = session.post(f"{BASE}/forum/posts",
                                json={"title": f"stress {i}", "body": "flood"},
                                headers=headers, timeout=TIMEOUT)
        if response.status_code in (200, 201):
            created.append(response.json()["post"]["id"])
        return response.status_code

    codes = _burst(_post)
    try:
        assert -1 not in codes, "the server dropped a connection under the forum flood"
        assert not [c for c in codes if c >= 500], f"forum flood produced server errors: {sorted(set(codes))}"
        assert 429 in codes, f"the forum rate-limit never engaged under a {len(codes)}-post flood: {sorted(set(codes))}"
        assert created, "the flood never landed a single post — the limiter is throttling normal use"
    finally:
        for post_id in created:  # deletes are capped at 20/min; the limiter admits well under that
            session.delete(f"{BASE}/forum/posts/{post_id}", headers=headers, timeout=TIMEOUT)


def test_readiness_never_returns_a_server_error_under_load():
    """/ready pings Mongo on every call — under pressure it must answer 200 or a clean 503, never 5xx."""
    session = requests.Session()
    codes = _burst(lambda _i: session.get(f"{BASE}/ready", timeout=TIMEOUT).status_code)
    assert -1 not in codes, "/ready hung or dropped the connection under load"
    assert set(codes) <= {200, 503}, f"/ready must degrade cleanly, saw {sorted(set(codes))}"
