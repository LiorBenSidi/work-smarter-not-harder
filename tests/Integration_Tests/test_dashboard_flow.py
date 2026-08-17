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


def test_dashboard_scores_from_the_latest_checkin_metrics(dash_client, monkeypatch):
    """The metrics that reach the model are the ones from the latest check-in, merged with the profile context — not a bare profile, and not a stale entry."""
    seen = {}

    def capture(url, features, **kw):
        # clear() FIRST: this test POSTs a check-in before reading the dashboard, and the check-in
        # calls predict too. Without the reset, `seen` still held the CHECK-IN's payload, so every
        # assertion below passed no matter what the dashboard sent. Measured: dropping the profile
        # from the dashboard's payload entirely left the whole suite green (measured) while this
        # test still asserted seen["goal"] == "maintain". Now it holds only the LAST call's features.
        seen.clear()
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


def test_dashboard_reports_which_check_in_it_scored(dash_client, fake_history, monkeypatch):
    """The dashboard reports the timestamp of the entry it scored, so the readiness card can name that day instead of calling every score today's check-in.

    Readiness comes from the LATEST check-in, which is only today's when the athlete checked in today.
    Two entries are seeded on different days; the reported timestamp must be the newer one's. Without it
    the card has nothing to distinguish a fresh score from a weeks-old one (issue #450).
    """
    _set_predict(monkeypatch, {"state": "Rest", "proba": {"Rest": 0.7}, "recommendations": []})
    _login(dash_client)
    metrics = {"sleep_hours": 8, "resting_hr": 55, "fatigue": 3, "soreness": 2, "training_load": 5}
    fake_history.add("alice", {"timestamp": "2026-07-19T06:30:00+00:00", "metrics": metrics, "assessment": "Rest"})
    fake_history.add("alice", {"timestamp": "2026-07-20T06:30:00+00:00", "metrics": metrics, "assessment": "Rest"})

    assert dash_client.get("/dashboard").get_json()["scored_at"] == "2026-07-20T06:30:00+00:00"


_RESOLVED_PLAN = {"split": "upper_lower",
                  "days": [{"day": 1, "focus": "Upper",
                            "exercises": [{"name": "Bench press", "sets": 4, "reps": "6-8",
                                           "muscle_group": "chest"}]}]}


def test_dashboard_relays_a_resolved_workout_plan(dash_client, monkeypatch):
    """The proposal's Dashboard shows the athlete's active workout plan, and the generator that builds it lives in the ai container — so the plan has to survive the trip through this route or the card has nothing to draw.

    The days are relayed unchanged: the exercise selection is the ai plane's decision, and re-shaping it
    here would put a second opinion about the workout in the courier.
    """
    _set_predict(monkeypatch, {"state": "Ready", "recommendations": [], "plan": _RESOLVED_PLAN})
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    plan = dash_client.get("/dashboard").get_json()["plan"]
    assert plan["split"] == "upper_lower"
    assert plan["days"] == _RESOLVED_PLAN["days"]          # relayed verbatim, not rebuilt
    assert "split_options" not in plan                     # a resolved plan asks the athlete nothing


def test_dashboard_relays_an_unresolved_plan_as_the_choice_it_is(dash_client, monkeypatch):
    """At 4 and 5 sessions a week two splits are equally defensible, so the generator returns both instead of guessing — and the dashboard must carry that choice through, because a guess made here would be indistinguishable to the athlete from a real recommendation."""
    _set_predict(monkeypatch, {"state": "Ready", "recommendations": [],
                               "plan": {"split_options": ["full_body", "upper_lower"]}})
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    plan = dash_client.get("/dashboard").get_json()["plan"]
    assert plan == {"split_options": ["full_body", "upper_lower"]}
    assert "split" not in plan                             # nothing was chosen on the athlete's behalf


@pytest.mark.parametrize("broken", [
    "upper_lower",                                          # a bare string, not the object the contract defines
    {"split": "upper_lower"},                               # resolved but no days -> a plan with nothing in it
    {"days": [{"day": 1}]},                                 # days with no split -> unattributable to a doctrine
    {"split": 4, "days": []},                               # split is not a name
    {"split_options": []},                                  # a choice with nothing to choose from
    {"split_options": ["full_body", 7]},                    # an option that cannot be rendered as a label
    {},                                                     # neither shape
])
def test_dashboard_drops_a_plan_that_breaks_the_contract(dash_client, monkeypatch, broken):
    """A plan that matches neither agreed shape is a contract break between containers, not a state the athlete is in — so it is reported as no plan rather than rendered as a partial one.

    Half a plan is worse than none: a split with no days reads as "your programme is empty", and a choice
    with no options renders a picker the athlete cannot answer. Readiness is unaffected either way, so the
    rest of the dashboard keeps working.
    """
    _set_predict(monkeypatch, {"state": "Ready", "recommendations": [], "plan": broken})
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    data = dash_client.get("/dashboard").get_json()
    assert data["plan"] is None
    assert data["ai_status"] == "ok"                        # one bad field does not condemn the prediction
    assert data["readiness"]["state"] == "Ready"


def test_dashboard_reports_no_plan_explicitly_when_the_ai_is_unreachable(dash_client, monkeypatch):
    """The key is present and null when the ai container is down, so the client tests one thing — is there a plan — instead of having to tell an absent key apart from an empty one."""
    _set_predict(monkeypatch, None)                        # ai unreachable
    _login(dash_client)
    dash_client.post("/profile", json=_profile())
    _checkin(dash_client)
    data = dash_client.get("/dashboard").get_json()
    assert data["ai_status"] == "unavailable"
    assert "plan" in data and data["plan"] is None          # present-and-null, not missing
