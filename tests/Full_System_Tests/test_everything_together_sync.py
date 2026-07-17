"""Full-system tests — EVERY feature wired into ONE app, focused on cross-feature SYNC. OWNER: Elad.

The per-feature suites prove each part behind its own seam; these prove the parts agree with each
other: a check-in is what History stores and what the Dashboard scores; a vote moves the score, the
author's notification feed AND the author's engagement metric; a DM lands in the recipient's inbox,
unread count and notification feed together. Everything runs in-process on the injected fakes (no
Mongo/Docker — the same DI seam the rest of the suite uses), with the AI client mocked at the
`services.ai_client.predict` boundary, so the whole matrix runs in the per-PR CI gate.

Two (or three) clients SHARE the same store instances — that's the sync under test: what user A does
through one session must be exactly what user B observes through another.
"""
import io
import sys

import pytest

_PNG = b"\x89PNG\r\n\x1a\nsync-bytes"
_AI_OK = {"state": "Ready", "proba": {"Ready": 0.9, "Moderate": 0.1}, "calories": 2100,
          "recommendations": ["train"]}
_METRICS = {"sleep_hours": 7.5, "resting_hr": 55, "fatigue": 3, "soreness": 2, "training_load": 6}


@pytest.fixture
def stack(make_client, fake_users, fake_profiles, fake_history, fake_forum, fake_messages,
          fake_media, fake_notifications, tmp_path, monkeypatch):
    """Three logged-in clients (alice/bob/carol) sharing ONE set of stores + a mockable AI seam."""

    def _client(name):
        c = make_client(fake_users, fake_profiles, history=fake_history, forum=fake_forum,
                        messages=fake_messages, media=fake_media, notifications=fake_notifications)
        c.raw.application.config["MEDIA_ROOT"] = str(tmp_path / "media")
        c.post("/register", json={"username": name, "password": "s3cretpw!", "email": name + "@ex.com"})
        c.post("/login", json={"username": name, "password": "s3cretpw!"})
        return c

    def _set_ai(fn):
        monkeypatch.setattr(sys.modules["services.ai_client"], "predict",
                            lambda url, features, **kw: fn(features))

    _set_ai(lambda f: dict(_AI_OK))
    return {"alice": _client("alice"), "bob": _client("bob"), "carol": _client("carol"),
            "set_ai": _set_ai}


# --------------------------------------------------------------- check-in -> history -> dashboard

def test_checkin_flows_to_history_and_dashboard(stack):
    a = stack["alice"]
    r = a.post("/checkin", json=_METRICS)
    assert r.status_code == 201 and r.get_json()["ai_status"] == "ok"
    # the SAME entry the check-in returned is what History lists...
    hist = a.get("/history").get_json()["history"]
    assert len(hist) == 1
    assert hist[0]["metrics"] == _METRICS
    assert hist[0]["assessment"] == "Ready" and hist[0]["calories"] == 2100
    # ...and what the Dashboard scores (it reads the latest entry's metrics).
    dash = a.get("/dashboard").get_json()
    assert dash["ai_status"] == "ok"
    assert dash["readiness"]["state"] == "Ready" and dash["calories"] == 2100


def test_second_checkin_same_day_replaces_not_duplicates(stack):
    # db.add_history keeps ONE row per UTC day (the fake mirrors it) — so a corrected check-in
    # must update History AND what the Dashboard scores, never fork a duplicate entry.
    a = stack["alice"]
    a.post("/checkin", json=_METRICS)
    corrected = {**_METRICS, "fatigue": 9}
    a.post("/checkin", json=corrected)
    hist = a.get("/history").get_json()["history"]
    assert len(hist) == 1, "a same-day re-check-in must replace, not append"
    assert hist[0]["metrics"]["fatigue"] == 9


def test_ai_down_checkin_saves_dashboard_degrades_history_consistent(stack):
    # Fault tolerance is a SYNC property too: with the AI dead the check-in still lands in History
    # (assessment None) and the Dashboard reports the same degraded state — no feature disagrees.
    stack["set_ai"](lambda f: None)
    a = stack["alice"]
    r = a.post("/checkin", json=_METRICS)
    assert r.status_code == 201 and r.get_json()["ai_status"] == "unavailable"
    hist = a.get("/history").get_json()["history"]
    assert len(hist) == 1 and hist[0]["assessment"] is None and hist[0]["calories"] is None
    dash = a.get("/dashboard").get_json()
    assert dash["ai_status"] == "unavailable" and dash["readiness"] is None


def test_dashboard_prompts_checkin_when_history_empty(stack):
    # No check-in -> nothing to score: the dashboard must say so instead of inventing a readiness.
    dash = stack["alice"].get("/dashboard").get_json()
    assert dash["needs_checkin"] is True and dash["readiness"] is None and dash["ai_status"] == "skipped"


# --------------------------------------------------------------- forum -> notifications -> engagement

def _post(client, title="sync post"):
    return client.post("/forum/posts", json={"title": title, "body": "body"}).get_json()["post"]["id"]


def test_vote_syncs_score_notification_and_engagement(stack):
    a, b = stack["alice"], stack["bob"]
    pid = _post(a)
    assert b.post(f"/forum/posts/{pid}/vote", json={"value": 1}).get_json()["score"] == 1
    # alice sees the moved score...
    assert a.get(f"/forum/posts/{pid}").get_json()["post"]["score"] == 1
    # ...a vote ping in her feed...
    notes = a.get("/notifications").get_json()
    assert any(n["type"] == "vote" for n in notes["notifications"]) and notes["unread"] >= 1
    # ...and the received-engagement metric counts the same event.
    assert a.get("/me/engagement").get_json() == {"up": 1, "down": 0, "score": 1}


def test_vote_toggle_score_stays_authoritative_and_pings_coalesce(stack):
    a, b = stack["alice"], stack["bob"]
    pid = _post(a)
    b.post(f"/forum/posts/{pid}/vote", json={"value": 1})
    assert b.post(f"/forum/posts/{pid}/vote", json={"value": -1}).get_json()["score"] == -1
    # one voter = one vote: the flip replaced it everywhere, and alice's engagement agrees.
    assert a.get(f"/forum/posts/{pid}").get_json()["post"]["score"] == -1
    assert a.get("/me/engagement").get_json() == {"up": 0, "down": 1, "score": -1}
    # anti-spam sync: rapid re-votes coalesce into ONE ping (the score is authoritative, the feed isn't a log).
    votes = [n for n in a.get("/notifications").get_json()["notifications"] if n["type"] == "vote"]
    assert len(votes) == 1


def test_comment_and_comment_vote_sync_across_users(stack):
    a, b = stack["alice"], stack["bob"]
    pid = _post(a)
    cid = b.post(f"/forum/posts/{pid}/comments", json={"body": "nice"}).get_json()["comment"]["id"]
    # alice's comments view shows bob's comment (#331: comments have their own endpoint)...
    comments = a.get(f"/forum/posts/{pid}/comments").get_json()["comments"]
    assert [c["id"] for c in comments] == [cid]
    # ...alice upvotes it -> the comment's score syncs into every view and BOB's engagement + feed.
    assert a.post(f"/forum/posts/{pid}/comments/{cid}/vote", json={"value": 1}).get_json()["score"] == 1
    assert b.get(f"/forum/posts/{pid}/comments").get_json()["comments"][0]["score"] == 1
    assert b.get("/me/engagement").get_json() == {"up": 1, "down": 0, "score": 1}
    assert any(n["type"] == "vote" for n in b.get("/notifications").get_json()["notifications"])


def test_anonymous_post_hides_author_from_others_but_still_notifies_them(stack):
    a, b = stack["alice"], stack["bob"]
    pid = a.post("/forum/posts", json={"title": "anon", "body": "hidden", "anonymous": True}
                 ).get_json()["post"]["id"]
    seen_by_b = b.get(f"/forum/posts/{pid}").get_json()["post"]
    assert seen_by_b["author"] == "Anonymous" and seen_by_b["mine"] is False
    # anonymity is a display projection — ownership (mine) and notification routing still work.
    assert a.get(f"/forum/posts/{pid}").get_json()["post"]["mine"] is True
    b.post(f"/forum/posts/{pid}/vote", json={"value": 1})
    assert any(n["type"] == "vote" for n in a.get("/notifications").get_json()["notifications"])


def test_self_vote_moves_score_but_never_pings_or_counts_engagement(stack):
    a = stack["alice"]
    pid = _post(a)
    assert a.post(f"/forum/posts/{pid}/vote", json={"value": 1}).get_json()["score"] == 1
    assert a.get("/notifications").get_json()["notifications"] == []
    assert a.get("/me/engagement").get_json() == {"up": 0, "down": 0, "score": 0}


# --------------------------------------------------------------- DMs -> inbox -> notifications

def test_dm_syncs_inbox_unread_notification_and_read_state(stack):
    a, b = stack["alice"], stack["bob"]
    assert a.post("/messages", json={"to": "bob", "body": "hi bob"}).status_code == 201
    # bob's inbox shows the conversation with the unread count...
    convos = b.get("/conversations").get_json()["conversations"]
    assert len(convos) == 1 and convos[0]["peer"] == "alice"
    assert convos[0]["last_message"] == "hi bob" and convos[0]["unread"] == 1
    # ...and his notification feed got the dm ping.
    assert any(n["type"] == "dm" for n in b.get("/notifications").get_json()["notifications"])
    # opening the thread clears the unread on the NEXT inbox read (read-state sync).
    thread = b.get("/conversations/alice").get_json()
    assert [m["body"] for m in thread["messages"]] == ["hi bob"]
    assert b.get("/conversations").get_json()["conversations"][0]["unread"] == 0
    # the sender sees the same thread from their side.
    assert [m["body"] for m in a.get("/conversations/bob").get_json()["messages"]] == ["hi bob"]


def test_dm_is_invisible_to_a_third_user(stack):
    a, c = stack["alice"], stack["carol"]
    a.post("/messages", json={"to": "bob", "body": "private"})
    assert c.get("/conversations").get_json()["conversations"] == []
    # a thread id is derived from {me, peer}: carol asking about alice gets THEIR (empty) thread,
    # never alice<->bob's.
    assert c.get("/conversations/alice").get_json()["messages"] == []


# --------------------------------------------------------------- media across forum + DMs

def _upload(client):
    r = client.post("/media", data={"file": (io.BytesIO(_PNG), "p.png", "image/png")})
    assert r.status_code == 201
    return r.get_json()["id"]


def test_media_visibility_tracks_its_binding(stack):
    a, b = stack["alice"], stack["bob"]
    mid = _upload(a)
    # unbound: uploader-only.
    assert a.get(f"/media/{mid}").status_code == 200
    assert b.get(f"/media/{mid}").status_code == 403
    # bound to a post: the forum is public to logged-in users -> bob can now see the bytes AND the listing.
    pid = _post(a, "with pic")
    assert a.post(f"/forum/posts/{pid}/attachments", json={"attachment_ids": [mid]}).get_json()["bound"] == [mid]
    assert b.get(f"/media/{mid}").status_code == 200
    assert [x["id"] for x in b.get(f"/forum/posts/{pid}/attachments").get_json()["attachments"]] == [mid]


def test_dm_attachment_visible_to_both_peers_never_a_third(stack):
    a, b, c = stack["alice"], stack["bob"], stack["carol"]
    mid = _upload(a)
    assert a.post("/messages/bob/attachments", json={"attachment_ids": [mid]}).get_json()["bound"] == [mid]
    assert b.get(f"/media/{mid}").status_code == 200        # the other participant
    assert c.get(f"/media/{mid}").status_code == 403        # anyone else
    # both peers resolve the SAME thread listing (order-independent conversation key).
    assert [x["id"] for x in b.get("/messages/alice/attachments").get_json()["attachments"]] == [mid]


# --------------------------------------------------------------- identity + erasure ripple

def test_display_name_change_ripples_to_forum_and_inbox(stack):
    a, b = stack["alice"], stack["bob"]
    pid = _post(a)
    a.post("/messages", json={"to": "bob", "body": "hello"})
    assert a.post("/account/display-name", json={"display_name": "Alice L."}).status_code == 200
    # every surface that shows alice now shows the NEW name (names resolve live, never denormalised).
    assert b.get(f"/forum/posts/{pid}").get_json()["post"]["author"] == "Alice L."
    assert b.get("/conversations").get_json()["conversations"][0]["peer_name"] == "Alice L."


def test_notifications_mark_read_syncs_unread_count(stack):
    a, b = stack["alice"], stack["bob"]
    pid = _post(a)
    b.post(f"/forum/posts/{pid}/vote", json={"value": 1})
    a.post("/messages", json={"to": "bob", "body": "yo"})     # bob: 1 dm ping; alice: 1 vote ping
    before = a.get("/notifications").get_json()
    assert before["unread"] == 1
    assert a.post("/notifications/read", json={}).status_code == 200   # no ids -> mark ALL read
    after = a.get("/notifications").get_json()
    assert after["unread"] == 0 and len(after["notifications"]) == len(before["notifications"])
