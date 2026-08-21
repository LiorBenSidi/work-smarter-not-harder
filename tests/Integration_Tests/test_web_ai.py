"""MANDATORY integration test — web -> ai. OWNER: Lior (web) + Shiri (ai).

The dashboard route (F7) calls ``ai_client.predict`` -> ai ``/predict``, then renders the returned
state. Here we stub ``ai_client.predict`` (the web->ai HTTP boundary) with a contract-shaped response
and assert GET /dashboard actually invokes it and surfaces the result — plus the graceful-degradation
path when ai is unreachable. In-process, so it needs no ai container.
"""
import sys
from unittest.mock import patch


def _login_with_profile_and_checkin(client, profiles, history):
    client.post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    client.post("/login", json={"username": "alice", "password": "s3cretpw!"})
    profiles.save("alice", {"age": 30, "goal": "maintain"})
    # The dashboard scores the LATEST check-in's metrics (routes/dashboard.py), so seed one — otherwise
    # there's nothing to score and the route short-circuits to needs_checkin without calling ai.
    history.add("alice", {"metrics": {"sleep_hours": 8, "resting_hr": 55,
                                      "fatigue": 3, "soreness": 2, "training_load": 5}})


def _ai_client(web_app_module):
    # web/app.py imported routes.dashboard -> services.ai_client while loading; it's cached in sys.modules.
    return sys.modules["services.ai_client"]


def test_dashboard_triggers_ai_predict_roundtrip(make_client, fake_users, fake_profiles, fake_history, web_app_module):
    """The dashboard genuinely CALLS the model service and surfaces what comes back — the state, the advice and the calorie target all reach the user.

    Asserting the call happened matters as much as the values: a route that quietly stopped asking would still render a plausible page.
    """
    client = make_client(fake_users, fake_profiles, history=fake_history)
    _login_with_profile_and_checkin(client, fake_profiles, fake_history)
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


def test_dashboard_degrades_when_ai_unreachable(make_client, fake_users, fake_profiles, fake_history, web_app_module):
    """With the model unreachable the page still loads and reports the score as unavailable, so one container being down never takes the whole app with it."""
    client = make_client(fake_users, fake_profiles, history=fake_history)
    _login_with_profile_and_checkin(client, fake_profiles, fake_history)
    with patch.object(_ai_client(web_app_module), "predict", return_value=None):   # ai down -> None
        resp = client.get("/dashboard")
    assert resp.status_code == 200                               # never crashes (fault tolerance)
    assert resp.get_json()["ai_status"] == "unavailable"


# ---------------------------------------------------------------------------
# The Advanced-tier programme input (#566). Until this shipped,
# ai/recommendations.py::_program_recommendations had been built and unit-tested
# since 12 Jul but had NO producer at all — web never sent the field it reads.
# These two tests cover the seam from both sides: web emits it, and ai consumes
# what web emits. A unit test on either side alone would still have passed while
# the feature did nothing.
# ---------------------------------------------------------------------------

def test_dashboard_sends_the_stored_programme_as_performed(make_client, fake_users, fake_profiles, fake_history, web_app_module):
    """The route must put the athlete's programme on the wire under ai's name and shape.

    Asserting the payload, not just that the call happened: a route that sent `training_program`
    verbatim would look identical from the outside and the analysis would silently see nothing.
    """
    client = make_client(fake_users, fake_profiles, history=fake_history)
    _login_with_profile_and_checkin(client, fake_profiles, fake_history)
    fake_profiles.save("alice", {"age": 30, "goal": "maintain",
                                 "training_program": {"chest": 18, "back": 12}})
    prediction = {"state": "Ready", "proba": {"Ready": 0.9}, "recommendations": [], "calories": 2400}
    with patch.object(_ai_client(web_app_module), "predict", return_value=prediction) as mock_predict:
        client.get("/dashboard")
    sent = mock_predict.call_args.args[1]
    assert sent["performed"] == [{"muscle_group": "chest", "sets": 18},
                                 {"muscle_group": "back", "sets": 12}]
    assert "training_program" not in sent


def test_what_web_sends_is_what_ai_can_actually_analyse(web_app_module):
    """The contract test between the two halves: run web's real payload through ai's real engine.

    This is the check that would have caught the original defect — `_program_recommendations` was
    correct, web's storage was correct, and the feature still produced nothing because the two sides
    never met. An imbalanced programme (chest 24 / back 4 — over the 20-set cap, under the 6-set
    floor, and outside the 0.67-1.5 pressing:pulling band) must produce real advice.
    """
    from ai.recommendations import generate_recommendations

    build_features = _ai_client(web_app_module).build_features
    features = build_features(
        {"age": 30, "goal": "maintain", "training_program": {"chest": 24, "back": 4}},
        {"sleep_hours": 8, "resting_hr": 55, "fatigue": 3, "soreness": 2, "training_load": 5},
    )
    advice = " ".join(generate_recommendations("Ready", features)).lower()
    assert "chest volume is high" in advice          # the over-volume rule fired
    assert "pulling volume" in advice                # the pressing:pulling ratio rule fired
    assert "back volume is low" in advice            # the under-volume rule fired
