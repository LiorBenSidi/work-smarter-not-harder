"""Integration tests for F7 dashboard — orchestrates profile + ai readiness. OWNER: Lior.

The dashboard scores readiness from the athlete's LATEST daily check-in metrics (merged with the
profile context) — the same payload the check-in flow sends. It must degrade gracefully when the ai
container is unreachable (DESIGN §5) — never crash. `ai_client.predict` is mocked so these run with no
ai container; a check-in is seeded first so there ARE metrics to score.
"""
import sys

import pytest


@pytest.fixture
def dash_client(make_client, fake_users, fake_profiles, fake_history):
    """A web client with an in-memory profile AND history store, so /checkin -> /dashboard round-trips
    without a real Mongo (the prod `_DbHistory` default a plain profile-only client would use)."""
    return make_client(fake_users, fake_profiles, history=fake_history)


def _login(c, username="alice"):
    c.post("/register", json={"username": username, "password": "s3cretpw!", "email": f"{username}@example.com"})
    c.post("/login", json={"username": username, "password": "s3cretpw!"})


def _profile():
    return {"age": 30, "gender": "male", "height": 180, "weight": 80, "goal": "maintain", "training_frequency": 3}


def _checkin(c, **over):
    """Log a valid daily check-in so the dashboard has a latest-metrics entry to score."""
    body = {"sleep_hours": 8, "resting_hr": 55, "fatigue": 3, "soreness": 2, "training_load": 5}
    body.update(over)
    return c.post("/checkin", json=body)


def _set_predict(monkeypatch, result):
    monkeypatch.setattr(sys.modules["services.ai_client"], "predict", lambda url, features, **kw: result)


def test_dashboard_without_profile_prompts_to_create_one(dash_client):
    _login(dash_client)
    data = dash_client.get("/dashboard").get_json()
    assert data["needs_profile"] is True
    assert data["readiness"] is None


def test_dashboard_with_profile_but_no_checkin_prompts_a_checkin(dash_client, monkeypatch):
    # Profile set, no check-in yet -> nothing to score. The dashboard must prompt a check-in, NOT fire a
    # profile-only /predict (which the model would 400) and NOT look like an AI outage.
    calls = []
    monkeypatch.setattr(sys.modules["services.ai_client"], "predict",
                        lambda *a, **k: calls.append((a, k)) or {"state": "Ready"})
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    data = dash_client.get("/dashboard").get_json()
    assert data["needs_checkin"] is True
    assert data["readiness"] is None
    assert data["ai_status"] == "skipped"
    assert calls == []                                   # no metrics -> predict never called


def test_dashboard_scores_from_the_latest_checkin_metrics(dash_client, monkeypatch):
    # The dashboard must send the latest check-in's metrics (merged with profile) to the ai — the four
    # readiness fields the model needs. Capture what predict receives.
    seen = {}

    def capture(url, features, **kw):
        seen.update(features)
        return {"state": "Ready", "proba": {"Ready": 0.9}, "recommendations": ["easy run"], "calories": 2500}

    monkeypatch.setattr(sys.modules["services.ai_client"], "predict", capture)
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client, sleep_hours=7, fatigue=4, soreness=3, training_load=6)
    data = dash_client.get("/dashboard").get_json()
    assert data["readiness"]["state"] == "Ready"
    # the latest check-in's readiness fields reached the model (not a bare profile)
    assert seen["sleep_hours"] == 7 and seen["fatigue"] == 4
    assert seen["soreness"] == 3 and seen["training_load"] == 6
    assert seen["goal"] == "maintain"                    # profile context merged in too


def test_dashboard_uses_the_most_recent_checkin(dash_client, monkeypatch):
    # Two check-ins: the dashboard scores the LATEST (oldest-first history -> [-1]).
    seen = {}

    def capture(url, features, **kw):
        seen.clear()
        seen.update(features)
        return {"state": "Rest", "recommendations": [], "calories": 2000}

    monkeypatch.setattr(sys.modules["services.ai_client"], "predict", capture)
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client, fatigue=2)
    _checkin(dash_client, fatigue=9)                  # the more recent one
    dash_client.get("/dashboard")
    assert seen["fatigue"] == 9


def test_dashboard_shows_readiness_and_calories_when_ai_responds(dash_client, monkeypatch):
    _set_predict(monkeypatch, {"state": "Ready", "proba": {"Ready": 0.9},
                               "recommendations": ["easy run"], "calories": 2500})
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    data = dash_client.get("/dashboard").get_json()
    assert data["readiness"]["state"] == "Ready"
    assert data["readiness"]["recommendations"] == ["easy run"]
    assert data["calories"] == 2500
    assert data["ai_status"] == "ok"


def test_dashboard_degrades_when_ai_unavailable(dash_client, monkeypatch):
    _set_predict(monkeypatch, None)  # ai unreachable -> ai_client.predict returns None
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    resp = dash_client.get("/dashboard")
    assert resp.status_code == 200  # graceful, not a crash
    body = resp.get_json()
    assert body["readiness"] is None
    assert body["ai_status"] == "unavailable"


def test_dashboard_degrades_when_ai_returns_non_object(dash_client, monkeypatch):
    _set_predict(monkeypatch, ["not", "a", "dict"])  # malformed AI response must not crash the page
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    resp = dash_client.get("/dashboard")
    assert resp.status_code == 200
    assert resp.get_json()["ai_status"] == "unavailable"


def test_dashboard_coerces_non_list_recommendations(dash_client, monkeypatch):
    # a buggy AI returning recommendations as a string must not leak a non-list to the client
    _set_predict(monkeypatch, {"state": "Ready", "recommendations": "go run", "calories": 2000})
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    data = dash_client.get("/dashboard").get_json()
    assert data["ai_status"] == "ok"
    assert data["readiness"]["recommendations"] == []


def test_dashboard_passes_through_proba_for_the_confidence_viz(dash_client, monkeypatch):
    # the per-state confidence drives the UI breakdown; numbers pass, non-numeric is dropped (defence).
    _set_predict(monkeypatch, {"state": "Ready", "recommendations": [],
                               "proba": {"Ready": 0.7, "Moderate": 0.2, "Rest": "boom"}, "calories": 2000})
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    proba = dash_client.get("/dashboard").get_json()["readiness"]["proba"]
    assert proba == {"Ready": 0.7, "Moderate": 0.2}       # the non-numeric "Rest" is sanitized out


def test_dashboard_proba_is_none_when_absent(dash_client, monkeypatch):
    _set_predict(monkeypatch, {"state": "Ready", "recommendations": [], "calories": 2000})
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    assert dash_client.get("/dashboard").get_json()["readiness"]["proba"] is None


def test_dashboard_drops_non_finite_ai_values_keeping_strict_json(dash_client, monkeypatch):
    # A buggy/hostile AI returning NaN/Infinity must NOT reach the response: jsonify serialises a
    # non-finite float as the bare tokens NaN/Infinity, which are invalid JSON that a browser's
    # JSON.parse rejects (blanking the dashboard). Non-finite proba/calories are dropped/nulled;
    # finite values survive; the body stays strict-valid JSON.
    import json
    _set_predict(monkeypatch, {"state": "Ready", "recommendations": [],
                               "proba": {"Ready": float("nan"), "Rest": 0.4, "Hard": float("inf")},
                               "calories": float("inf")})
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    resp = dash_client.get("/dashboard")
    assert resp.status_code == 200
    # strict parse: parse_constant fires on any bare NaN/Infinity/-Infinity token -> raise -> test fails
    json.loads(resp.get_data(as_text=True),
               parse_constant=lambda tok: (_ for _ in ()).throw(ValueError(f"non-finite JSON token: {tok}")))
    data = resp.get_json()
    assert data["readiness"]["proba"] == {"Rest": 0.4}   # non-finite proba keys dropped, the finite one kept
    assert data["calories"] is None                       # non-finite calories -> null
