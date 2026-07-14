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
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    assert c.post("/checkin", json=_metrics()).status_code == 401


def test_checkin_rejects_bad_metrics_400(make_client, fake_users, fake_profiles, fake_history):
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    assert c.post("/checkin", json={"sleep_hours": 7.5}).status_code == 400          # missing fields
    assert c.post("/checkin", json={**_metrics(), "fatigue": {"$gt": ""}}).status_code == 400  # injection
    assert c.post("/checkin", json={**_metrics(), "fatigue": 999}).status_code == 400  # out of range
    assert c.post("/checkin", json={**_metrics(), "resting_hr": "55"}).status_code == 400  # string, not a number
    assert c.post("/checkin", json={**_metrics(), "sleep_hours": True}).status_code == 400  # bool


def test_checkin_ignores_url_query_params(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    # UI-bypass guard: /checkin reads ONLY the JSON body, so smuggling metrics in the URL query string can't
    # work. A hostile query is ignored (a valid body still succeeds), and an out-of-range BODY is still
    # rejected regardless of the query string — a curl / URL-param bypass of the client-side validation fails.
    _set_predict(monkeypatch, {"state": "Ready", "calories": 2000})
    c = _client(make_client, fake_users, fake_profiles, fake_history)
    _login(c)
    assert c.post("/checkin?fatigue=999&sleep_hours=0", json=_metrics()).status_code == 201       # query ignored
    assert c.post("/checkin?fatigue=3", json={**_metrics(), "fatigue": 999}).status_code == 400   # body still validated


def test_checkin_still_saved_when_ai_down(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
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
    _set_predict(monkeypatch, {"state": "Ready"})
    c = make_client(fake_users, fake_profiles, history=_BrokenHistory())
    _login(c)
    assert c.post("/checkin", json=_metrics()).status_code == 503


def test_checkin_nulls_non_finite_calories(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    # A non-finite calories from the AI must be neither persisted nor emitted as an invalid-JSON token
    # (jsonify would write a bare Infinity/NaN that a browser's JSON.parse rejects).
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
