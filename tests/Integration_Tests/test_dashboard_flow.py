"""Integration tests for F7 dashboard — orchestrates profile + ai readiness. OWNER: Lior.

The dashboard must degrade gracefully when the ai container is unreachable (DESIGN §5) — never crash.
`ai_client.predict` is mocked so these run with no ai container.
"""
import sys


def _login(c, username="alice"):
    c.post("/register", json={"username": username, "password": "s3cretpw!"})
    c.post("/login", json={"username": username, "password": "s3cretpw!"})


def _profile():
    return {"age": 30, "gender": "male", "height": 180, "weight": 80, "goal": "maintain", "training_frequency": 3}


def _set_predict(monkeypatch, result):
    monkeypatch.setattr(sys.modules["services.ai_client"], "predict", lambda url, features, **kw: result)


def test_dashboard_without_profile_prompts_to_create_one(profile_client):
    _login(profile_client)
    data = profile_client.get("/dashboard").get_json()
    assert data["needs_profile"] is True
    assert data["readiness"] is None


def test_dashboard_shows_readiness_and_calories_when_ai_responds(profile_client, monkeypatch):
    _set_predict(monkeypatch, {"state": "Ready", "proba": {"Ready": 0.9},
                               "recommendations": ["easy run"], "calories": 2500})
    _login(profile_client)
    profile_client.post("/profile", json=_profile())
    data = profile_client.get("/dashboard").get_json()
    assert data["readiness"]["state"] == "Ready"
    assert data["readiness"]["recommendations"] == ["easy run"]
    assert data["calories"] == 2500
    assert data["ai_status"] == "ok"


def test_dashboard_degrades_when_ai_unavailable(profile_client, monkeypatch):
    _set_predict(monkeypatch, None)  # ai unreachable -> ai_client.predict returns None
    _login(profile_client)
    profile_client.post("/profile", json=_profile())
    resp = profile_client.get("/dashboard")
    assert resp.status_code == 200  # graceful, not a crash
    body = resp.get_json()
    assert body["readiness"] is None
    assert body["ai_status"] == "unavailable"


def test_dashboard_degrades_when_ai_returns_non_object(profile_client, monkeypatch):
    _set_predict(monkeypatch, ["not", "a", "dict"])  # malformed AI response must not crash the page
    _login(profile_client)
    profile_client.post("/profile", json=_profile())
    resp = profile_client.get("/dashboard")
    assert resp.status_code == 200
    assert resp.get_json()["ai_status"] == "unavailable"


def test_dashboard_coerces_non_list_recommendations(profile_client, monkeypatch):
    # a buggy AI returning recommendations as a string must not leak a non-list to the client
    _set_predict(monkeypatch, {"state": "Ready", "recommendations": "go run", "calories": 2000})
    _login(profile_client)
    profile_client.post("/profile", json=_profile())
    data = profile_client.get("/dashboard").get_json()
    assert data["ai_status"] == "ok"
    assert data["readiness"]["recommendations"] == []
