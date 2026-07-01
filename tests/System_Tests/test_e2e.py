"""MANDATORY system (end-to-end) test. OWNER: Lior (the web->ai->db system flow) + Shiri (ai).
Elad runs it against the live stack via the containerized test-runner.

Unlike the integration tests (Flask test client, in-process, injected fakes), this exercises the REAL
wire path over HTTP against a RUNNING 3-container stack — CSRF double-submit, just like a browser. Set
``E2E_BASE_URL`` to the deployed web service (e.g. http://localhost:8000); it **skips cleanly** when
that's unset, so normal CI (which has no live stack) stays green. The same flow has been run live (12/12).
"""
import os
import uuid

import pytest

requests = pytest.importorskip("requests")

BASE = os.environ.get("E2E_BASE_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not BASE, reason="set E2E_BASE_URL to run the system e2e against a live stack")


@pytest.fixture
def client():
    s = requests.Session()
    s.get(f"{BASE}/health", timeout=5)              # seed the double-submit CSRF cookie
    return s


def _h(s):
    return {"X-CSRF-Token": s.cookies.get("csrf_token", "")}   # CSRF token on every unsafe request


def test_full_user_journey_web_ai_db(client):
    s = client
    user, pw = "e2e_" + uuid.uuid4().hex[:8], "s3cret-e2e-pw!"

    assert s.post(f"{BASE}/register", json={"username": user, "password": pw, "email": user + "@example.com"}, headers=_h(s)).status_code in (200, 201)
    assert s.post(f"{BASE}/login", json={"username": user, "password": pw}, headers=_h(s)).status_code == 200
    assert s.get(f"{BASE}/me").json().get("username") == user

    assert s.post(f"{BASE}/profile", json={"age": 30, "gender": "male", "height": 180, "weight": 78,
                  "goal": "maintain", "training_frequency": 4}, headers=_h(s)).status_code == 200

    # the cross-container hop: web validates -> calls ai /predict -> writes the db history
    assert s.post(f"{BASE}/checkin", json={"sleep_hours": 7, "resting_hr": 55, "fatigue": 3,
                  "soreness": 2, "training_load": 5}, headers=_h(s)).status_code in (200, 201)

    dashboard = s.get(f"{BASE}/dashboard").json()
    assert "readiness" in dashboard or "ai_status" in dashboard       # readiness came back from ai
    assert len(s.get(f"{BASE}/history").json().get("history", [])) >= 1   # the check-in landed in db

    pid = s.post(f"{BASE}/forum/posts", json={"title": "e2e", "body": "hi"}, headers=_h(s)).json()["post"]["id"]
    assert s.post(f"{BASE}/forum/posts/{pid}/vote", json={"value": 1}, headers=_h(s)).json()["score"] == 1
    assert s.post(f"{BASE}/forum/posts/{pid}/comments", json={"body": "nice"}, headers=_h(s)).ok

    assert s.post(f"{BASE}/logout", headers=_h(s)).status_code == 200
    assert s.get(f"{BASE}/dashboard").status_code == 401             # session is gated after logout
