"""The dashboard reports PROPOSAL-v2 §3's Beginner / Intermediate / Advanced tier. OWNER: Lior.

#528 item 3. The tier is derived here from the profile alone — it needs no `ai` call, which is why it
survives an outage and is reported before the first check-in.

Kept in its own file rather than appended to `test_dashboard_flow.py` so it does not collide with
work in flight on that area.

`ai_client.predict` is mocked throughout: these assert what the *web tier* does, not what the model
computes.
"""
import sys

import pytest


@pytest.fixture
def dash_client(make_client, fake_users, fake_profiles, fake_history):
    return make_client(fake_users, fake_profiles, history=fake_history)


def _login(c, username="tiers"):
    c.post("/register", json={"username": username, "password": "s3cretpw!", "email": f"{username}@example.com"})
    c.post("/login", json={"username": username, "password": "s3cretpw!"})


def _checkin(c):
    return c.post("/checkin", json={"sleep_hours": 8, "resting_hr": 55, "fatigue": 3, "soreness": 2, "training_load": 5})


def _set_predict(monkeypatch, result):
    monkeypatch.setattr(sys.modules["services.ai_client"], "predict", lambda url, features, **kw: result)


def _prediction(**over):
    body = {"state": "Ready", "proba": {"Ready": 0.7}, "recommendations": [], "plan": None}
    body.update(over)
    return body


BASE = {"age": 30, "gender": "male", "height": 180, "weight": 80, "goal": "maintain", "training_frequency": 3}


# --------------------------------------------------------------- item 3: the tier

@pytest.mark.parametrize("extra,expected", [
    ({}, "beginner"),
    ({"equipment": ["bands"]}, "intermediate"),
    ({"split_preference": "upper_lower"}, "intermediate"),
    ({"training_program": {"chest": 12, "back": 8}}, "advanced"),
])
def test_the_tier_reported_matches_what_the_athlete_filled_in(dash_client, monkeypatch, extra, expected):
    _login(dash_client)
    dash_client.post("/profile", json={**BASE, **extra})
    _checkin(dash_client)
    _set_predict(monkeypatch, _prediction())
    assert dash_client.get("/dashboard").get_json()["tier"] == expected


def test_the_tier_is_reported_before_the_first_check_in(dash_client, monkeypatch):
    """The tier is derived from the profile, so a brand-new athlete who has saved one but not yet
    checked in should still be told which tier they are in -- that is the path §3's Beginner is on."""
    _login(dash_client)
    dash_client.post("/profile", json=BASE)
    data = dash_client.get("/dashboard").get_json()
    assert data["needs_checkin"] is True
    assert data["tier"] == "beginner"


def test_the_tier_survives_an_ai_outage(dash_client, monkeypatch):
    """It needs no ai call, so an unreachable container must not take it down with readiness
    (fault tolerance -- DESIGN §5)."""
    _login(dash_client)
    dash_client.post("/profile", json={**BASE, "training_program": {"chest": 12}})
    _checkin(dash_client)
    _set_predict(monkeypatch, None)
    data = dash_client.get("/dashboard").get_json()
    assert data["ai_status"] == "unavailable"
    assert data["tier"] == "advanced"


def test_a_user_with_no_profile_has_no_tier(dash_client, monkeypatch):
    _login(dash_client)
    _checkin(dash_client)
    _set_predict(monkeypatch, _prediction())
    assert dash_client.get("/dashboard").get_json()["tier"] is None


def test_the_tier_gates_nothing_a_lower_tier_would_otherwise_receive(dash_client, monkeypatch):
    """The tier NAMES the structure §3 promises; it must never withhold an output. A beginner gets
    the same readiness, recommendations, calories and plan an advanced athlete does."""
    _login(dash_client)
    dash_client.post("/profile", json=BASE)                       # beginner
    _checkin(dash_client)
    _set_predict(monkeypatch, _prediction(calories=2500,
                                          recommendations=["Sleep more."],
                                          plan={"split": "full_body", "days": [{"day": 1, "focus": "Full"}]}))
    data = dash_client.get("/dashboard").get_json()
    assert data["tier"] == "beginner"
    assert data["calories"] == 2500
    assert data["readiness"]["recommendations"] == ["Sleep more."]
    assert data["plan"]["split"] == "full_body"


def test_adding_a_programme_promotes_the_tier_on_the_next_read(dash_client, monkeypatch):
    """Derived, not stored: the label has to move the moment the profile does, with no migration."""
    _login(dash_client)
    dash_client.post("/profile", json=BASE)
    _checkin(dash_client)
    _set_predict(monkeypatch, _prediction())
    assert dash_client.get("/dashboard").get_json()["tier"] == "beginner"
    dash_client.post("/profile", json={**BASE, "training_program": {"chest": 12}})
    assert dash_client.get("/dashboard").get_json()["tier"] == "advanced"
