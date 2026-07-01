"""MANDATORY integration test — web -> ai. OWNER: Lior (web) + Shiri (ai).

The dashboard route (F7) calls ``ai_client.predict`` -> ai ``/predict``, then renders the returned
state. Here we stub ``ai_client.predict`` (the web->ai HTTP boundary) with a contract-shaped response
and assert GET /dashboard actually invokes it and surfaces the result — plus the graceful-degradation
path when ai is unreachable. In-process, so it needs no ai container.
"""
import sys
from unittest.mock import patch


def _login_with_profile(client, profiles):
    client.post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    client.post("/login", json={"username": "alice", "password": "s3cretpw!"})
    profiles.save("alice", {"age": 30, "goal": "maintain"})


def _ai_client(web_app_module):
    # web/app.py imported routes.dashboard -> services.ai_client while loading; it's cached in sys.modules.
    return sys.modules["services.ai_client"]


def test_dashboard_triggers_ai_predict_roundtrip(make_client, fake_users, fake_profiles, web_app_module):
    client = make_client(fake_users, fake_profiles)
    _login_with_profile(client, fake_profiles)
    prediction = {"state": "Ready", "proba": {"Ready": 0.9},
                  "recommendations": ["hydrate", "sleep 8h"], "calories": 2400}
    with patch.object(_ai_client(web_app_module), "predict", return_value=prediction) as mock_predict:
        resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert mock_predict.called                                   # the route made the web->ai call
    body = resp.get_json()
    assert body["ai_status"] == "ok"
    assert body["readiness"]["state"] == "Ready"                 # ai's state surfaced by the route
    assert body["readiness"]["recommendations"] == ["hydrate", "sleep 8h"]
    assert body["calories"] == 2400


def test_dashboard_degrades_when_ai_unreachable(make_client, fake_users, fake_profiles, web_app_module):
    client = make_client(fake_users, fake_profiles)
    _login_with_profile(client, fake_profiles)
    with patch.object(_ai_client(web_app_module), "predict", return_value=None):   # ai down -> None
        resp = client.get("/dashboard")
    assert resp.status_code == 200                               # never crashes (fault tolerance)
    assert resp.get_json()["ai_status"] == "unavailable"
