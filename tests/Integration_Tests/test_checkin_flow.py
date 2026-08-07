"""Integration tests for the daily check-in flow (F3 input). OWNER: Lior.

POST /checkin validates today's metrics, forwards them (+ profile context) to the ai container, and
records the assessment in analysis_history. It degrades gracefully when the ai container is down
(the check-in is still saved, assessment unavailable) and is auth-gated. `ai_client.predict` is mocked.
"""
import sys


def _login(c, username="alice"):
    c.post("/register", json={"username": username, "password": "s3cretpw!", "email": f"{username}@example.com"})
    c.post("/login", json={"username": username, "password": "s3cretpw!"})


def _metrics():
    return {"sleep_hours": 7.5, "resting_hr": 55, "fatigue": 3, "soreness": 2, "training_load": 6}


def _set_predict(monkeypatch, result):
    monkeypatch.setattr(sys.modules["services.ai_client"], "predict", lambda url, features, **kw: result)


def _client(make_client, fake_users, fake_profiles, fake_history):
    return make_client(fake_users, fake_profiles, history=fake_history)


def test_checkin_saves_assessment_to_history(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    """A check-in is scored and lands in history in the exact shape the history view renders, so what the user just submitted is what they find when they look back."""
    _set_predict(monkeypatch, {"state": "Ready", "calories": 2200})
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    resp = c.post("/checkin", json=_metrics())
    assert resp.status_code == 201
    body = resp.get_json()
    assert body["ai_status"] == "ok"
    assert body["entry"]["assessment"] == "Ready"
    assert body["entry"]["calories"] == 2200
    assert body["entry"]["timestamp"]                       # a timestamp was stamped
    # the entry is now in history, in the shape /history renders
    hist = c.get("/history").get_json()["history"]
    assert len(hist) == 1
    assert hist[0]["assessment"] == "Ready"


def test_checkin_requires_login(make_client, fake_users, fake_profiles, fake_history):
    """A check-in belongs to an account, so an anonymous submission is refused rather than stored against nobody."""
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    assert c.post("/checkin", json=_metrics()).status_code == 401


def test_checkin_rejects_bad_metrics_400(make_client, fake_users, fake_profiles, fake_history):
    """Every class of bad input is refused at the ROUTE — missing fields, an operator object, out of range, a numeric string, a bool — so the client-side validation is a convenience rather than the only line of defence."""
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    assert c.post("/checkin", json={"sleep_hours": 7.5}).status_code == 400          # missing fields
    assert c.post("/checkin", json={**_metrics(), "fatigue": {"$gt": ""}}).status_code == 400  # injection
    assert c.post("/checkin", json={**_metrics(), "fatigue": 999}).status_code == 400  # out of range
    assert c.post("/checkin", json={**_metrics(), "resting_hr": "55"}).status_code == 400  # string, not a number
    assert c.post("/checkin", json={**_metrics(), "sleep_hours": True}).status_code == 400  # bool


def test_checkin_ignores_url_query_params(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    """The route reads only the JSON body, so metrics smuggled into the query string are ignored and an out-of-range body is still refused.

    Someone bypassing the form with a hand-written request gets nowhere.
    """
    _set_predict(monkeypatch, {"state": "Ready", "calories": 2000})
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    assert c.post("/checkin?fatigue=999&sleep_hours=0", json=_metrics()).status_code == 201       # query ignored
    assert c.post("/checkin?fatigue=3", json={**_metrics(), "fatigue": 999}).status_code == 400   # body still validated


def test_checkin_still_saved_when_ai_down(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    """When the model is unreachable the check-in is STILL saved and the response says the score is unavailable, so a user's own data is never lost to somebody else's outage."""
    _set_predict(monkeypatch, None)  # ai unreachable
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    resp = c.post("/checkin", json=_metrics())
    assert resp.status_code == 201                          # graceful, not a crash
    body = resp.get_json()
    assert body["ai_status"] == "unavailable"
    assert body["entry"]["assessment"] is None
    assert c.get("/history").get_json()["history"][0]["metrics"]["sleep_hours"] == 7.5  # metrics still recorded


class _BrokenHistory:
    def list(self, *a):
        return []

    def add(self, *a):
        raise RuntimeError("down")


def test_checkin_degrades_to_503_when_history_store_fails(make_client, fake_users, fake_profiles, monkeypatch):
    """If the entry cannot be stored the request fails honestly instead of reporting success for data that went nowhere."""
    _set_predict(monkeypatch, {"state": "Ready"})
    c = make_client(fake_users, fake_profiles, history=_BrokenHistory())
    _login(c)
    assert c.post("/checkin", json=_metrics()).status_code == 503


def test_checkin_nulls_non_finite_calories(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    """A non-finite number from the model is neither persisted nor emitted, because the JSON encoder would write a bare token that a browser refuses to parse.

    That breaks the ENTIRE response, not just the one field — so the test parses the body strictly to prove no such token survives.
    """
    import json
    _set_predict(monkeypatch, {"state": "Ready", "calories": float("inf")})
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    resp = c.post("/checkin", json=_metrics())
    assert resp.status_code == 201
    json.loads(resp.get_data(as_text=True),
               parse_constant=lambda tok: (_ for _ in ()).throw(ValueError(f"non-finite JSON token: {tok}")))
    assert resp.get_json()["entry"]["calories"] is None                      # non-finite -> null in the response
    assert c.get("/history").get_json()["history"][0]["calories"] is None    # and never persisted to history


def test_checkin_persists_proba_for_the_real_history_score(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    """History could only show three banded levels because just the state word was stored; keeping the per-state probabilities lets it compute the same fine-grained score the dashboard shows.

    Only finite values are kept, so a malformed probability cannot poison the stored entry.
    """
    _set_predict(monkeypatch, {"state": "Ready", "calories": 2200,
                               "proba": {"Ready": 0.82, "Moderate": 0.1, "Rest": 0.08, "bogus": float("nan")}})
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    entry = c.post("/checkin", json=_metrics()).get_json()["entry"]
    assert entry["proba"] == {"Ready": 0.82, "Moderate": 0.1, "Rest": 0.08}   # finite kept, NaN dropped
    stored = c.get("/history").get_json()["history"][0]
    assert stored["proba"]["Ready"] == 0.82                                   # ...and it's persisted


def test_checkin_missing_proba_persists_none(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    """A response without probabilities stores an explicit absence rather than a fabricated default that would render as a real score."""
    _set_predict(monkeypatch, {"state": "Ready", "calories": 2000})           # no proba in the AI response
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    assert c.post("/checkin", json=_metrics()).get_json()["entry"]["proba"] is None


def test_checkin_persists_recommendations_for_the_detail_view(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    """The per-entry detail view shows what was advised AT THE TIME, so the advice is stored alongside the entry — coerced to strings, because it is rendered as text."""
    _set_predict(monkeypatch, {"state": "Ready", "calories": 2200,
                               "recommendations": ["Hydrate well", "Push your planned session", 42]})
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    entry = c.post("/checkin", json=_metrics()).get_json()["entry"]
    assert entry["recommendations"] == ["Hydrate well", "Push your planned session", "42"]   # coerced to strings
    stored = c.get("/history").get_json()["history"][0]
    assert stored["recommendations"] == ["Hydrate well", "Push your planned session", "42"]   # ...and persisted


def test_checkin_missing_recommendations_persists_empty_list(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    """No advice in the response yields an empty list rather than a missing key, so the detail view can iterate it without a guard."""
    _set_predict(monkeypatch, {"state": "Ready", "calories": 2000})           # no recommendations key
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    assert c.post("/checkin", json=_metrics()).get_json()["entry"]["recommendations"] == []


# ---- #354 backfill: regenerate recommendations for a PRE-#354 check-in (stored before recs were persisted) ----
def _old_entry(ts="2026-06-01T07:00:00Z", **extra):
    e = {"assessment": "Ready", "timestamp": ts, "metrics": dict(_metrics())}
    e.update(extra)
    return e


def test_regenerate_recommendations_backfills_from_the_entrys_inputs(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    """An entry stored before advice was persisted can regenerate it from the metrics it did keep, so older history is not permanently blank."""
    fake_history.add("alice", _old_entry())                                   # no `recommendations` key (pre-#354)
    _set_predict(monkeypatch, {"state": "Ready", "recommendations": ["Push your session", 7]})
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    r = c.post("/history/recommendations", json={"timestamp": "2026-06-01T07:00:00Z"})
    assert r.status_code == 200
    assert r.get_json()["recommendations"] == ["Push your session", "7"]      # regenerated + coerced to strings
    stored = c.get("/history").get_json()["history"][0]
    assert stored["recommendations"] == ["Push your session", "7"]            # ...and persisted onto the entry


def test_regenerate_recommendations_is_idempotent_and_skips_the_ai(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    """An entry that already has advice returns it WITHOUT calling the model, so re-opening an old entry does not queue work that has already been done."""
    fake_history.add("alice", _old_entry(ts="2026-06-02T07:00:00Z", recommendations=["Already here"]))
    def _boom(*a, **k):
        raise AssertionError("the ai must not be called when recommendations already exist")
    monkeypatch.setattr(sys.modules["services.ai_client"], "predict", _boom)
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    r = c.post("/history/recommendations", json={"timestamp": "2026-06-02T07:00:00Z"})
    assert r.status_code == 200 and r.get_json()["recommendations"] == ["Already here"]


def test_regenerate_recommendations_404_for_an_unknown_entry(make_client, fake_users, fake_profiles, fake_history):
    """Backfilling an entry that does not exist is a 404, so a stale client cannot conjure a record that was never checked in."""
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    assert c.post("/history/recommendations", json={"timestamp": "does-not-exist"}).status_code == 404


def test_regenerate_recommendations_503_when_the_ai_is_down(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    """With the model unreachable the backfill reports unavailable rather than writing an empty result, which would leave the entry looking permanently answered."""
    fake_history.add("alice", _old_entry(ts="2026-06-03T07:00:00Z"))
    _set_predict(monkeypatch, None)                                          # ai unreachable
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    assert c.post("/history/recommendations", json={"timestamp": "2026-06-03T07:00:00Z"}).status_code == 503


def test_regenerate_recommendations_requires_login(make_client, fake_users, fake_profiles, fake_history):
    """The backfill reads and writes a user's own history, so it is gated like every other route that touches it."""
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    assert c.post("/history/recommendations", json={"timestamp": "x"}).status_code == 401


def test_second_checkin_same_day_replaces_the_days_entry(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    """A daily readiness log is one row per day: a second check-in on the same day REPLACES the first rather than accruing several rows, and the later one wins.

    Without this a user who corrects a typo ends up with two contradictory entries for one morning.
    """
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    _set_predict(monkeypatch, {"state": "Rest", "calories": 2100})
    c.post("/checkin", json={**_metrics(), "fatigue": 9})
    _set_predict(monkeypatch, {"state": "Ready", "calories": 2600})
    c.post("/checkin", json={**_metrics(), "fatigue": 2})
    hist = c.get("/history").get_json()["history"]
    assert len(hist) == 1                                                     # one row for today, not two
    assert hist[0]["assessment"] == "Ready" and hist[0]["calories"] == 2600   # the LATEST wins
    assert hist[0]["metrics"]["fatigue"] == 2
