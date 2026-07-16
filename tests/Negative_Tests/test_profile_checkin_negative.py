"""Negative tests — profile + daily check-in validation walls. OWNER: Elad.

Every boundary of `validate_profile` / `validate_checkin` from the WRONG side: each field one step
out of range on both ends, wrong-typed (str / bool / list / injection object), missing, and the
payload itself malformed. Bounds mirror the single-source-of-truth tables in the routes
(`profile.py`'s validators, `checkin.py`'s CHECKIN_FIELDS) — if a bound moves there, the matching
case here moves with it.
"""
import pytest

GOOD_PROFILE = {"age": 25, "gender": "other", "height": 175.0, "weight": 72.5,
                "goal": "maintain", "training_frequency": 4}
GOOD_METRICS = {"sleep_hours": 7.5, "resting_hr": 55, "fatigue": 3, "soreness": 2, "training_load": 6}


@pytest.fixture
def user_client(profile_client):
    profile_client.post("/register", json={"username": "negp", "password": "s3cretpw!", "email": "p@ex.com"})
    profile_client.post("/login", json={"username": "negp", "password": "s3cretpw!"})
    return profile_client


@pytest.fixture
def checkin_client(make_client, fake_users, fake_profiles, fake_history, monkeypatch):
    import sys
    monkeypatch.setattr(sys.modules["services.ai_client"], "predict",
                        lambda url, features, **kw: {"state": "Ready", "calories": 2000})
    c = make_client(fake_users, fake_profiles, history=fake_history)
    c.post("/register", json={"username": "negc", "password": "s3cretpw!", "email": "c@ex.com"})
    c.post("/login", json={"username": "negc", "password": "s3cretpw!"})
    return c


# --------------------------------------------------------------- profile field walls

@pytest.mark.parametrize("field,bad", [
    ("age", 9), ("age", 121),                     # one out of range on each side (10-120)
    ("age", 25.5),                                # age is integer-only
    ("age", True), ("age", "25"), ("age", {"$gt": 0}), ("age", None),
    ("height", 49), ("height", 301),              # 50-300
    ("weight", 19), ("weight", 501),              # 20-500
    ("training_frequency", -1), ("training_frequency", 15),   # 0-14
    ("training_frequency", 3.5),                  # integer-only
    ("gender", ""), ("gender", "x" * 33), ("gender", 7), ("gender", None),
    ("goal", "get-swole"), ("goal", ""), ("goal", 1), ("goal", ["lose"]),
])
def test_profile_rejects_each_bad_field(user_client, field, bad):
    r = user_client.post("/profile", json={**GOOD_PROFILE, field: bad})
    assert r.status_code == 400, f"{field}={bad!r} must be refused, got {r.status_code}"
    assert field in r.get_json()["error"]


@pytest.mark.parametrize("field", sorted(GOOD_PROFILE))
def test_profile_rejects_each_missing_field(user_client, field):
    payload = {k: v for k, v in GOOD_PROFILE.items() if k != field}
    assert user_client.post("/profile", json=payload).status_code == 400


@pytest.mark.parametrize("payload", [None, [], "profile", 42])
def test_profile_rejects_a_non_object_payload(user_client, payload):
    assert user_client.post("/profile", json=payload).status_code == 400


def test_a_rejected_profile_is_never_partially_saved(user_client):
    # validation is all-or-nothing: after a refusal the store must hold NOTHING new.
    user_client.post("/profile", json={**GOOD_PROFILE, "age": 999})
    assert user_client.get("/profile").get_json()["profile"] is None


def test_profile_extra_unknown_fields_are_dropped_not_stored(user_client):
    # a smuggled field (e.g. an $-operator key) must never reach the store.
    r = user_client.post("/profile", json={**GOOD_PROFILE, "$set": {"admin": True}, "role": "admin"})
    assert r.status_code == 200
    saved = user_client.get("/profile").get_json()["profile"]
    assert set(saved) == set(GOOD_PROFILE)


# --------------------------------------------------------------- check-in field walls

@pytest.mark.parametrize("field,bad", [
    ("sleep_hours", 0.5), ("sleep_hours", 25),    # 1-24 (model floor: >= 1)
    ("resting_hr", 29), ("resting_hr", 221),      # 30-220
    ("resting_hr", 55.5),                         # integer-only
    ("fatigue", 0), ("fatigue", 11),              # 1-10
    ("soreness", 0), ("soreness", 11),            # 1-10
    ("training_load", -1), ("training_load", 11), # 0-10
    ("fatigue", True), ("fatigue", "3"), ("fatigue", {"$gt": 0}), ("fatigue", None),
])
def test_checkin_rejects_each_bad_metric(checkin_client, field, bad):
    r = checkin_client.post("/checkin", json={**GOOD_METRICS, field: bad})
    assert r.status_code == 400, f"{field}={bad!r} must be refused, got {r.status_code}"
    assert field in r.get_json()["error"]


@pytest.mark.parametrize("field", sorted(GOOD_METRICS))
def test_checkin_rejects_each_missing_metric(checkin_client, field):
    payload = {k: v for k, v in GOOD_METRICS.items() if k != field}
    assert checkin_client.post("/checkin", json=payload).status_code == 400


@pytest.mark.parametrize("payload", [None, [], "metrics", {}])
def test_checkin_rejects_a_non_object_or_empty_payload(checkin_client, payload):
    assert checkin_client.post("/checkin", json=payload).status_code == 400


def test_a_rejected_checkin_never_reaches_history(checkin_client):
    checkin_client.post("/checkin", json={**GOOD_METRICS, "fatigue": 99})
    assert checkin_client.get("/history").get_json()["history"] == []
