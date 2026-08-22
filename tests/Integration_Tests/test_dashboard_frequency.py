"""The dashboard relays PROPOSAL-v2 §3's "Recommended training frequency". OWNER: Lior.

#528 item 1, **web half only**. The value itself is produced by the recommendation engine, which
REPORT §6 places in the AI lane; this file covers what the *web tier* does with it — relay it, guard
it, or drop it. Until the `ai` half exists, `/predict` omits the field and the pill renders nothing,
which `test_an_ai_that_omits_the_field_leaves_the_dashboard_working` pins as the expected state
rather than a failure.

Kept in its own file rather than appended to `test_dashboard_flow.py` so it does not collide with
work in flight on that area.

`ai_client.predict` is mocked throughout, so these run with no ai container.
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


# --------------------------------------------------------------- item 1: the frequency relay

@pytest.mark.parametrize("value", [0, 1, 4, 7])
def test_the_recommended_frequency_reaches_the_client(dash_client, monkeypatch, value):
    """§3 lists it as a Beginner output, so it has to arrive in the payload the dashboard renders.

    Swept across the ai contract's whole stated range rather than one value, because both ends are
    where a relay guard goes wrong: `0` is a deload week and was previously dropped as if absent
    (caught in review on #590), and `7` is the last trainable week before the guard should reject.
    """
    _login(dash_client)
    dash_client.post("/profile", json=BASE)
    _checkin(dash_client)
    _set_predict(monkeypatch, _prediction(recommended_frequency=value))
    assert dash_client.get("/dashboard").get_json()["recommended_frequency"] == value


@pytest.mark.parametrize("bad", [
    float("nan"), float("inf"), float("-inf"),   # would serialise as invalid-JSON tokens
    8, 14, -3,                                   # outside the ai contract's 0-7 range
    "4", None, True, [4], {"sessions": 4},       # wrong type (bool is an int subclass -- excluded)
])
def test_a_frequency_the_web_tier_cannot_stand_behind_is_dropped_not_rendered(dash_client, monkeypatch, bad):
    """The relay is a guard, not a pipe. A NaN would reach the browser as invalid JSON and a 14-session
    week is not a week anyone can train, so both become null rather than output.

    `0` is deliberately NOT here: it is inside the ai contract's 0-7 range (a deload week), and dropping
    it silently was the same class of bug as #582/#583 -- a real zero read as absent. It is asserted as
    a *passing* value above instead."""
    _login(dash_client)
    dash_client.post("/profile", json=BASE)
    _checkin(dash_client)
    _set_predict(monkeypatch, _prediction(recommended_frequency=bad))
    assert dash_client.get("/dashboard").get_json()["recommended_frequency"] is None


def test_an_ai_that_omits_the_field_leaves_the_dashboard_working(dash_client, monkeypatch):
    """The field is optional in the ai contract, so an older ai build must not break the dashboard."""
    _login(dash_client)
    dash_client.post("/profile", json=BASE)
    _checkin(dash_client)
    _set_predict(monkeypatch, _prediction())
    data = dash_client.get("/dashboard").get_json()
    assert data["recommended_frequency"] is None
    assert data["readiness"]["state"] == "Ready"


def test_the_relayed_frequency_is_not_the_one_the_athlete_typed(dash_client, monkeypatch):
    """End-to-end restatement of the rule the ai unit tests pin: what the dashboard shows must be a
    recommendation, not the profile's own `training_frequency` reflected back."""
    _login(dash_client)
    dash_client.post("/profile", json={**BASE, "training_frequency": 7})
    _checkin(dash_client)
    _set_predict(monkeypatch, _prediction(recommended_frequency=3))
    data = dash_client.get("/dashboard").get_json()
    assert data["recommended_frequency"] == 3
    assert data["profile"]["training_frequency"] == 7
