"""MANDATORY fault-tolerance system test — OWNER: Elad.

The course rule: an AI or DB outage must NOT take the user-facing service down. The in-process test
``tests/Integration_Tests/test_web_ai.py`` proves the *code path* degrades when ``ai_client.predict``
returns None. This proves the *deployment* does: it stops a real container and re-probes the real web
service over HTTP.

    /health  liveness   -> stays 200 with ai down AND with db down (course rule: Mongo-independent,
                           otherwise Docker's healthcheck would kill the container during a DB blip)
    /ready   readiness  -> stays 200 with ai down (ai is non-critical); 503 with db down (db is core)

Destructive: it stops and restarts containers, so it is DOUBLE-gated — it runs only when
``FAULT_TEST=1`` **and** ``E2E_BASE_URL`` are both set, i.e. never in the normal CI run and never by
accident against a stack you care about. It always restarts what it stopped (``finally``).

    docker compose up --build -d
    FAULT_TEST=1 E2E_BASE_URL=http://localhost:8000 python -m pytest tests/System_Tests/test_fault_isolation.py -v
"""
import os
import shutil
import subprocess
import time

import pytest

requests = pytest.importorskip("requests")

BASE = os.environ.get("E2E_BASE_URL", "").rstrip("/")
# Which compose file(s) the stack was started with — must match, or `docker compose stop` targets nothing.
COMPOSE_FILES = os.environ.get("COMPOSE_FILES", "docker-compose.yml").split(",")

pytestmark = [
    pytest.mark.skipif(os.environ.get("FAULT_TEST") != "1",
                       reason="destructive (stops containers) — set FAULT_TEST=1 to run"),
    pytest.mark.skipif(not BASE, reason="set E2E_BASE_URL to the live stack"),
    pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not available"),
]

PROBE_TIMEOUT = 10
SETTLE_ATTEMPTS = 15      # how long we allow web to notice the outage / the service to come back
SETTLE_DELAY = 2


def _compose(*args):
    cmd = ["docker", "compose"]
    for f in COMPOSE_FILES:
        cmd += ["-f", f.strip()]
    subprocess.run(cmd + list(args), check=True, capture_output=True, timeout=180)


def _probe(path):
    """Status code of GET path, or -1 if web itself is unreachable (that would be the real failure)."""
    try:
        return requests.get(f"{BASE}{path}", timeout=PROBE_TIMEOUT).status_code
    except requests.RequestException:
        return -1


def _wait_for(path, expected):
    """Poll until `path` returns `expected` (returns True) or we run out of attempts (returns False)."""
    for _ in range(SETTLE_ATTEMPTS):
        if _probe(path) == expected:
            return True
        time.sleep(SETTLE_DELAY)
    return False


@pytest.fixture
def stopped():
    """Stop a named service for the duration of a test, then always bring it back and let it settle."""
    stopped_service = {}

    def _stop(service):
        stopped_service["name"] = service
        _compose("stop", service)

    yield _stop

    if "name" in stopped_service:
        _compose("start", stopped_service["name"])
        _wait_for("/ready", 200)   # don't leak a half-down stack into the next test


def test_web_survives_the_ai_container_going_down(stopped):
    """AI is non-critical: stopping it must not touch liveness OR readiness of the web tier."""
    assert _probe("/health") == 200, "precondition: the stack is up before we break it"
    stopped("ai")

    assert _probe("/health") == 200, "web died when ai stopped — the AI outage was not isolated"
    assert _probe("/ready") == 200, "ai is non-critical: /ready must not report the stack unready"


def test_web_survives_the_db_container_going_down(stopped):
    """DB is core: liveness must hold (or Docker kills web), but readiness must honestly report 503."""
    assert _probe("/health") == 200, "precondition: the stack is up before we break it"
    stopped("db")

    assert _wait_for("/ready", 503), "/ready must turn 503 when Mongo is unreachable"
    assert _probe("/health") == 200, (
        "/health must stay 200 with the DB down — it is liveness, and Docker's healthcheck "
        "would otherwise restart web during every DB blip"
    )
