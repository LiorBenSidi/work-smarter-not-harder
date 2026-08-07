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


def test_dashboard_new_user_prompts_a_checkin_and_flags_the_missing_profile(dash_client):
    """A brand-new user cannot be scored yet, so the dashboard asks for the check-in the model actually needs and separately flags the missing profile for the calorie target."""
    _login(dash_client)
    data = dash_client.get("/dashboard").get_json()
    assert data["needs_checkin"] is True
    assert data["needs_profile"] is True
    assert data["readiness"] is None


def test_dashboard_shows_readiness_without_a_profile(dash_client, monkeypatch):
    """Someone who has checked in sees their readiness even WITHOUT a profile — the model scores on the daily metrics alone, and the profile only adds the calorie target.

    The missing profile stays a soft hint rather than a hard block, and only the metrics reach the model.
    """
    seen = {}

    def capture(url, features, **kw):
        seen.clear()
        seen.update(features)
        return {"state": "Rest", "proba": {"Rest": 0.8}, "recommendations": ["recover"]}  # no calories w/o profile

    monkeypatch.setattr(sys.modules["services.ai_client"], "predict", capture)
    _login(dash_client)
    _checkin(dash_client, sleep_hours=6, fatigue=8, soreness=7, training_load=4)   # NO profile posted
    data = dash_client.get("/dashboard").get_json()
    assert data["readiness"]["state"] == "Rest"          # readiness shows despite no profile
    assert data["ai_status"] == "ok"
    assert data["needs_profile"] is True                 # soft hint for the calorie target
    assert data["calories"] is None                      # calories needs a profile
    assert "goal" not in seen                             # only the metrics reached the model (no profile keys)
    assert seen["fatigue"] == 8


def test_dashboard_with_profile_but_no_checkin_prompts_a_checkin(dash_client, monkeypatch):
    """With a profile but no check-in there is nothing to score, so the dashboard asks for one instead of firing a profile-only prediction the model would reject — which would read to the user as an outage."""
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
    """The metrics that reach the model are the ones from the latest check-in, merged with the profile context — not a bare profile, and not a stale entry."""
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


def test_dashboard_forwards_recent_history_for_trend_recs(dash_client, fake_history, monkeypatch):
    """Trend-aware advice — a streak of hard days, declining sleep, a load spike — needs recent history, so the dashboard forwards it.

    Only the two fields the engine reads are sent per entry, keeping the payload small; the engine's own logic is tested separately, so what is proven here is the WIRING.
    """
    seen = {}

    def capture(url, features, **kw):
        seen.clear()
        seen.update(features)
        return {"state": "Rest", "proba": {"Rest": 0.8}, "recommendations": ["recover"]}

    monkeypatch.setattr(sys.modules["services.ai_client"], "predict", capture)
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    day_metrics = {"sleep_hours": 5, "resting_hr": 55, "fatigue": 8, "soreness": 6, "training_load": 7}
    for day in ("2026-06-26", "2026-06-27", "2026-06-28"):   # three DISTINCT days -> a genuine 3x Rest streak
        fake_history.add("alice", {"timestamp": day + "T07:00:00+00:00", "assessment": "Rest",
                                   "metrics": dict(day_metrics)})
    dash_client.get("/dashboard")                        # the call whose payload we inspect (fires last)

    history = seen.get("history")
    assert isinstance(history, list) and len(history) == 3
    for entry in history:                                # each entry is exactly the two fields the engine uses
        assert set(entry) == {"metrics", "assessment"}
        assert entry["assessment"] == "Rest"             # stored from the mocked predict state
        assert isinstance(entry["metrics"], dict) and entry["metrics"]["fatigue"] == 8


def test_dashboard_history_forwarded_is_bounded_and_empty_history_is_harmless(dash_client, monkeypatch):
    """A single check-in still produces a well-formed history list, so a brand-new athlete is unaffected by the trend feature rather than hitting a missing key."""
    seen = {}

    def capture(url, features, **kw):
        seen.clear()
        seen.update(features)
        return {"state": "Ready", "proba": {"Ready": 0.9}, "recommendations": ["go"], "calories": 2500}

    monkeypatch.setattr(sys.modules["services.ai_client"], "predict", capture)
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    dash_client.get("/dashboard")
    assert seen.get("history") == [{"metrics": {"sleep_hours": 8, "resting_hr": 55, "fatigue": 3,
                                                 "soreness": 2, "training_load": 5}, "assessment": "Ready"}]


def test_dashboard_uses_the_most_recent_checkin(dash_client, fake_history, monkeypatch):
    """The dashboard scores the LATEST entry, proven across distinct days.

    The earlier version submitted two check-ins back to back, but same-day replacement collapses those into one row — so it was selecting from a single-element list and could not tell the newest from the oldest.
    """
    seen = {}

    def capture(url, features, **kw):
        seen.clear()
        seen.update(features)
        return {"state": "Rest", "recommendations": [], "calories": 2000}

    monkeypatch.setattr(sys.modules["services.ai_client"], "predict", capture)
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    base = {"sleep_hours": 7, "resting_hr": 55, "soreness": 2, "training_load": 5}
    fake_history.add("alice", {"timestamp": "2026-06-26T07:00:00+00:00", "assessment": "Ready",
                               "metrics": {**base, "fatigue": 2}})          # older
    fake_history.add("alice", {"timestamp": "2026-06-27T07:00:00+00:00", "assessment": "Rest",
                               "metrics": {**base, "fatigue": 9}})          # the more recent one
    dash_client.get("/dashboard")
    assert seen["fatigue"] == 9


def test_dashboard_shows_readiness_and_calories_when_ai_responds(dash_client, monkeypatch):
    """The happy path: a healthy prediction reaches the user as a readiness state, its advice, and a calorie target."""
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
    """An unreachable model leaves the page loading successfully with the score marked unavailable, rather than failing the whole dashboard over one absent number."""
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
    """A malformed response is treated as unavailable rather than crashing the page mid-render — the failure mode of trusting a reply's shape."""
    _set_predict(monkeypatch, ["not", "a", "dict"])  # malformed AI response must not crash the page
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    resp = dash_client.get("/dashboard")
    assert resp.status_code == 200
    assert resp.get_json()["ai_status"] == "unavailable"


def test_dashboard_coerces_non_list_recommendations(dash_client, monkeypatch):
    """Advice that arrives as a bare string is not passed through as one, because the client iterates it — a string would render one character per line."""
    _set_predict(monkeypatch, {"state": "Ready", "recommendations": "go run", "calories": 2000})
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    data = dash_client.get("/dashboard").get_json()
    assert data["ai_status"] == "ok"
    assert data["readiness"]["recommendations"] == []


def test_dashboard_passes_through_proba_for_the_confidence_viz(dash_client, monkeypatch):
    """The per-state confidence drives the breakdown the user sees, so numbers pass through and a non-numeric value is dropped rather than reaching a chart that cannot plot it."""
    _set_predict(monkeypatch, {"state": "Ready", "recommendations": [],
                               "proba": {"Ready": 0.7, "Moderate": 0.2, "Rest": "boom"}, "calories": 2000})
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    proba = dash_client.get("/dashboard").get_json()["readiness"]["proba"]
    assert proba == {"Ready": 0.7, "Moderate": 0.2}       # the non-numeric "Rest" is sanitized out


def test_dashboard_proba_is_none_when_absent(dash_client, monkeypatch):
    """A prediction without confidence figures reports their absence explicitly, so the interface hides the breakdown instead of drawing an empty one."""
    _set_predict(monkeypatch, {"state": "Ready", "recommendations": [], "calories": 2000})
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    assert dash_client.get("/dashboard").get_json()["readiness"]["proba"] is None


def test_dashboard_drops_non_finite_ai_values_keeping_strict_json(dash_client, monkeypatch):
    """A non-finite number from the model must never reach the response: the encoder writes it as a bare token that is invalid JSON, and the browser then fails to parse the WHOLE body — blanking the dashboard over one bad field.

    The body is parsed strictly here, so any such token fails the test rather than shipping.
    """
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


def test_dashboard_history_read_is_bounded(dash_client, fake_history, monkeypatch):
    """The dashboard needs the latest check-in and a short recent window, so its history read is capped rather than loading a user's entire append-only log on every page view.

    Dropping the bound makes the store see no limit at all, which is exactly what this catches.
    """
    from services.db import HISTORY_VIEW_CAP
    _set_predict(monkeypatch, {"state": "Rest", "proba": {"Rest": 0.8}, "recommendations": []})
    _login(dash_client)
    _checkin(dash_client)

    seen = {}
    original = fake_history.list

    def spy(username, limit=None):
        seen["limit"] = limit                 # capture the bound the ROUTE requested (checkin already ran)
        return original(username, limit=limit)

    monkeypatch.setattr(fake_history, "list", spy)
    assert dash_client.get("/dashboard").status_code == 200
    assert seen["limit"] == HISTORY_VIEW_CAP  # bounded, not None (which would be the unbounded export read)
