"""Regression tests for the LOW/MED hardening items from the data-field + RLS audits. OWNER: Lior.

These close, with explicit tests, the three findings that were "latent, not currently exploitable":
non-finite numbers, a non-string `ids` element, and the notification actor leaking the internal handle.
"""
import sys


def _register(client, name, email):
    return client.post("/register", json={"username": name, "password": "s3cretpw!", "email": email})


def _login(client, ident):
    return client.post("/login", json={"username": ident, "password": "s3cretpw!"})


def test_checkin_and_profile_reject_non_finite_numbers(web_app_module):
    # NaN/Infinity now fail an EXPLICIT finiteness check, not just the range bound (so the defense
    # survives a future widened bound). Validators are pure functions -> call them directly.
    validate_checkin = sys.modules["routes.checkin"].validate_checkin
    validate_profile = sys.modules["routes.profile"].validate_profile
    checkin = {"sleep_hours": 7, "resting_hr": 60, "fatigue": 5, "soreness": 5, "training_load": 5}
    profile = {"age": 30, "gender": "x", "height": 175, "weight": 70, "goal": "maintain", "training_frequency": 3}
    for bad in (float("nan"), float("inf"), float("-inf")):
        for fn, base, field in ((validate_checkin, checkin, "sleep_hours"), (validate_profile, profile, "height")):
            try:
                fn(dict(base, **{field: bad}))
                assert False, f"{bad} accepted for {field}"
            except ValueError as exc:
                assert "finite" in str(exc)


def test_mark_notifications_read_rejects_a_non_string_id(messages_client):
    # a hostile {"ids": [{"$gt": ""}]} used to reach set(ids) -> TypeError -> 503; now it's a clean 400.
    _register(messages_client, "eddie", "eddie@example.com")
    _login(messages_client, "eddie")
    resp = messages_client.post("/notifications/read", json={"ids": [{"$gt": ""}]})
    assert resp.status_code == 400
    resp2 = messages_client.post("/notifications/read", json={"ids": [123, "ok"]})
    assert resp2.status_code == 400


def test_notification_actor_is_the_display_name_not_the_internal_handle(forum_client):
    # the forum hides handles (shows display names); a vote notification must not re-expose the voter's
    # handle. Use a SUFFIXED voter (handle "voter-2", display "voter") so handle != display name.
    _register(forum_client, "poster", "poster@example.com")
    _register(forum_client, "voter", "voter1@example.com")           # handle "voter"
    _register(forum_client, "voter", "voter2@example.com")           # handle "voter-2", display "voter"
    _login(forum_client, "poster")
    pid = forum_client.post("/forum/posts", json={"title": "t", "body": "b"}).get_json()["post"]["id"]
    _login(forum_client, "voter2@example.com")                       # the suffixed voter
    forum_client.post("/forum/posts/" + pid + "/vote", json={"value": 1})
    _login(forum_client, "poster")
    votes = [n for n in forum_client.get("/notifications").get_json()["notifications"] if n["type"] == "vote"]
    assert votes and votes[0]["actor"] == "voter"                    # display name
    assert votes[0]["actor"] != "voter-2"                            # never the internal handle
