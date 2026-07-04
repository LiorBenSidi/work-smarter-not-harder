"""Integration tests for F7 dashboard — orchestrates profile + ai readiness. OWNER: Lior.

The dashboard must degrade gracefully when the ai container is unreachable (DESIGN §5) — never crash.
`ai_client.predict` is mocked so these run with no ai container.
"""
import sys


def _login(c, username="alice"):
    c.post("/register", json={"username": username, "password": "s3cretpw!", "email": f"{username}@example.com"})
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


def test_dashboard_passes_through_proba_for_the_confidence_viz(profile_client, monkeypatch):
    # the per-state confidence drives the UI breakdown; numbers pass, non-numeric is dropped (defence).
    _set_predict(monkeypatch, {"state": "Ready", "recommendations": [],
                               "proba": {"Ready": 0.7, "Moderate": 0.2, "Rest": "boom"}, "calories": 2000})
    _login(profile_client)
    profile_client.post("/profile", json=_profile())
    proba = profile_client.get("/dashboard").get_json()["readiness"]["proba"]
    assert proba == {"Ready": 0.7, "Moderate": 0.2}       # the non-numeric "Rest" is sanitized out


def test_dashboard_proba_is_none_when_absent(profile_client, monkeypatch):
    _set_predict(monkeypatch, {"state": "Ready", "recommendations": [], "calories": 2000})
    _login(profile_client)
    profile_client.post("/profile", json=_profile())
    assert profile_client.get("/dashboard").get_json()["readiness"]["proba"] is None


def test_dashboard_drops_non_finite_ai_values_keeping_strict_json(profile_client, monkeypatch):
    # A buggy/hostile AI returning NaN/Infinity must NOT reach the response: jsonify serialises a
    # non-finite float as the bare tokens NaN/Infinity, which are invalid JSON that a browser's
    # JSON.parse rejects (blanking the dashboard). Non-finite proba/calories are dropped/nulled;
    # finite values survive; the body stays strict-valid JSON.
    import json
    _set_predict(monkeypatch, {"state": "Ready", "recommendations": [],
                               "proba": {"Ready": float("nan"), "Rest": 0.4, "Hard": float("inf")},
                               "calories": float("inf")})
    _login(profile_client)
    profile_client.post("/profile", json=_profile())
    resp = profile_client.get("/dashboard")
    assert resp.status_code == 200
    # strict parse: parse_constant fires on any bare NaN/Infinity/-Infinity token -> raise -> test fails
    json.loads(resp.get_data(as_text=True),
               parse_constant=lambda tok: (_ for _ in ()).throw(ValueError(f"non-finite JSON token: {tok}")))
    data = resp.get_json()
    assert data["readiness"]["proba"] == {"Rest": 0.4}   # non-finite proba keys dropped, the finite one kept
    assert data["calories"] is None                       # non-finite calories -> null
