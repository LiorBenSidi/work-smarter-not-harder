"""Full-system tests — each part STANDALONE, and each part BROKEN while the rest keep serving. OWNER: Elad.

The mirror image of `test_everything_together_sync.py`: first that every feature works with only ITS
OWN stores wired (no hidden coupling — auth doesn't secretly need the forum, check-in doesn't need a
profile), then fault isolation INSIDE the web tier — one store blowing up must degrade only its own
feature (clean 503 / best-effort skip), never a neighbour. In-process on the injected fakes; the AI
seam is mocked. This is the same "web survives ai/db death" contract the live fault-isolation suite
proves across containers (`System_Tests/test_fault_isolation.py`), pushed down to per-feature grain.
"""
import sys

import pytest

_METRICS = {"sleep_hours": 7.5, "resting_hr": 55, "fatigue": 3, "soreness": 2, "training_load": 6}
_AI_OK = {"state": "Ready", "proba": {"Ready": 0.9}, "calories": 2100, "recommendations": []}


class Boom:
    """A store whose EVERY method raises — the in-process stand-in for a dead Mongo collection."""

    def __getattr__(self, name):
        def _raise(*a, **k):
            raise RuntimeError(f"store method {name} exploded (simulated outage)")
        return _raise


def _signup(c, name="solo"):
    c.post("/register", json={"username": name, "password": "s3cretpw!", "email": name + "@ex.com"})
    c.post("/login", json={"username": name, "password": "s3cretpw!"})
    return name


@pytest.fixture
def mock_ai(monkeypatch):
    def _set(fn):
        monkeypatch.setattr(sys.modules["services.ai_client"], "predict",
                            lambda url, features, **kw: fn(features))
    _set(lambda f: dict(_AI_OK))
    return _set


# --------------------------------------------------------------- each part standalone

def test_auth_works_with_only_the_user_store(make_client, fake_users):
    c = make_client(fake_users)
    _signup(c)
    me = c.get("/me")
    assert me.status_code == 200 and me.get_json()["username"] == "solo"
    assert c.post("/logout").status_code == 200
    assert c.get("/me").status_code == 401


def test_profile_roundtrip_needs_only_users_and_profiles(make_client, fake_users, fake_profiles):
    c = make_client(fake_users, fake_profiles)
    _signup(c)
    body = {"age": 30, "gender": "other", "height": 180.0, "weight": 80.0,
            "goal": "gain", "training_frequency": 3}
    assert c.post("/profile", json=body).status_code == 200
    assert c.get("/profile").get_json()["profile"] == body


def test_checkin_works_without_any_profile(make_client, fake_users, fake_profiles, fake_history, mock_ai):
    # The profile is calorie context only — a brand-new user's first action can be a check-in.
    c = make_client(fake_users, fake_profiles, history=fake_history)
    _signup(c)
    r = c.post("/checkin", json=_METRICS)
    assert r.status_code == 201 and r.get_json()["ai_status"] == "ok"
    assert len(c.get("/history").get_json()["history"]) == 1


def test_dashboard_shows_readiness_without_a_profile(make_client, fake_users, fake_profiles,
                                                     fake_history, mock_ai):
    # Issue #266's contract: no profile must NOT gate readiness — it only flags the calorie target.
    c = make_client(fake_users, fake_profiles, history=fake_history)
    _signup(c)
    c.post("/checkin", json=_METRICS)
    dash = c.get("/dashboard").get_json()
    assert dash["readiness"]["state"] == "Ready"
    assert dash["needs_profile"] is True


def test_forum_crud_needs_only_forum_and_notifications(make_client, fake_users, fake_forum,
                                                       fake_notifications):
    c = make_client(fake_users, forum=fake_forum, notifications=fake_notifications)
    _signup(c)
    pid = c.post("/forum/posts", json={"title": "t", "body": "b"}).get_json()["post"]["id"]
    assert c.post(f"/forum/posts/{pid}/vote", json={"value": 1}).get_json()["score"] == 1
    assert c.post(f"/forum/posts/{pid}/comments", json={"body": "c"}).status_code == 201
    assert c.delete(f"/forum/posts/{pid}").status_code == 200
    assert c.get(f"/forum/posts/{pid}").status_code == 404


def test_dms_need_only_messages_and_notifications(make_client, fake_users, fake_messages,
                                                  fake_notifications):
    c = make_client(fake_users, messages=fake_messages, notifications=fake_notifications)
    _signup(c, "alice")
    c.post("/register", json={"username": "bob", "password": "s3cretpw!", "email": "bob@ex.com"})
    assert c.post("/messages", json={"to": "bob", "body": "hi"}).status_code == 201
    assert [m["body"] for m in c.get("/conversations/bob").get_json()["messages"]] == ["hi"]


def test_media_upload_and_owner_serve_need_only_the_media_store(make_client, fake_users, fake_media,
                                                                tmp_path):
    import io
    c = make_client(fake_users, media=fake_media)
    c.raw.application.config["MEDIA_ROOT"] = str(tmp_path / "m")
    _signup(c)
    r = c.post("/media", data={"file": (io.BytesIO(b"\x89PNG\r\n\x1a\nx"), "p.png", "image/png")})
    assert r.status_code == 201
    assert c.get(f"/media/{r.get_json()['id']}").status_code == 200


# --------------------------------------------------------------- one part broken, the rest serve

def test_dead_forum_store_degrades_forum_only(make_client, fake_users, fake_messages,
                                              fake_notifications):
    c = make_client(fake_users, forum=Boom(), messages=fake_messages, notifications=fake_notifications)
    _signup(c, "alice")
    c.post("/register", json={"username": "bob", "password": "s3cretpw!", "email": "bob@ex.com"})
    assert c.get("/forum/posts").status_code == 503                      # its own feature: clean 503
    assert c.post("/forum/posts", json={"title": "t", "body": "b"}).status_code == 503
    assert c.get("/me").status_code == 200                               # neighbours: untouched
    assert c.post("/messages", json={"to": "bob", "body": "hi"}).status_code == 201


def test_dead_history_store_degrades_checkin_and_dashboard_only(make_client, fake_users, fake_profiles,
                                                                fake_forum, fake_notifications, mock_ai):
    c = make_client(fake_users, fake_profiles, history=Boom(), forum=fake_forum,
                    notifications=fake_notifications)
    _signup(c)
    assert c.post("/checkin", json=_METRICS).status_code == 503
    assert c.get("/dashboard").status_code == 503
    assert c.get("/history").status_code == 503
    assert c.post("/forum/posts", json={"title": "t", "body": "b"}).status_code == 201
    assert c.get("/profile").status_code == 200


def test_dead_notifications_never_fail_the_action_they_decorate(make_client, fake_users, fake_forum,
                                                                fake_messages):
    # Vote pings and DM pings are best-effort by contract — the primary action must land regardless.
    c = make_client(fake_users, forum=fake_forum, messages=fake_messages, notifications=Boom())
    _signup(c, "alice")
    c.post("/register", json={"username": "bob", "password": "s3cretpw!", "email": "bob@ex.com"})
    pid = c.post("/forum/posts", json={"title": "t", "body": "b"}).get_json()["post"]["id"]
    assert c.post(f"/forum/posts/{pid}/vote", json={"value": 1}).status_code == 200
    assert c.post("/messages", json={"to": "bob", "body": "hi"}).status_code == 201
    # only the feed itself degrades.
    assert c.get("/notifications").status_code == 503


def test_dead_profile_store_degrades_profile_and_checkin_only(make_client, fake_users, fake_history,
                                                              fake_forum, fake_notifications, mock_ai):
    # check-in reads the profile for AI context -> it must 503 cleanly; the forum doesn't care.
    c = make_client(fake_users, Boom(), history=fake_history, forum=fake_forum,
                    notifications=fake_notifications)
    _signup(c)
    assert c.get("/profile").status_code == 503
    assert c.post("/checkin", json=_METRICS).status_code == 503
    assert c.post("/forum/posts", json={"title": "t", "body": "b"}).status_code == 201


def test_ai_down_degrades_ai_features_only(make_client, fake_users, fake_profiles, fake_history,
                                           fake_forum, fake_messages, fake_notifications, mock_ai):
    mock_ai(lambda f: None)   # the client's "unreachable" signal
    c = make_client(fake_users, fake_profiles, history=fake_history, forum=fake_forum,
                    messages=fake_messages, notifications=fake_notifications)
    _signup(c, "alice")
    c.post("/register", json={"username": "bob", "password": "s3cretpw!", "email": "bob@ex.com"})
    # AI-dependent features degrade (still 2xx — the check-in is SAVED, the dashboard reports it)...
    r = c.post("/checkin", json=_METRICS)
    assert r.status_code == 201 and r.get_json()["ai_status"] == "unavailable"
    assert c.get("/dashboard").get_json()["ai_status"] == "unavailable"
    # ...everything else is oblivious.
    assert c.post("/forum/posts", json={"title": "t", "body": "b"}).status_code == 201
    assert c.post("/messages", json={"to": "bob", "body": "hi"}).status_code == 201
    assert c.get("/history").status_code == 200
