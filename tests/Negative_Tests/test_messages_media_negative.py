"""Negative tests — DMs + media refuse bad input, hostile targets and privacy breaches. OWNER: Elad.

The messaging rejection contract (self-DM, unknown recipient, injection payloads, the in-store
anti-spam window) and the media walls (missing/forbidden file, per-file size cap via 413, unknown
blob, foreign-blob serve/bind, third-party DM attachment reads).
"""
import io

import pytest

_PNG = b"\x89PNG\r\n\x1a\nneg-bytes"


@pytest.fixture
def alice(media_client):
    media_client.post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "a@ex.com"})
    media_client.post("/login", json={"username": "alice", "password": "s3cretpw!"})
    return media_client


@pytest.fixture
def bob(make_client, fake_users, fake_forum, fake_messages, fake_media, fake_notifications, tmp_path):
    # a second client SHARING alice's stores (same tmp media root the media_client fixture set).
    c = make_client(fake_users, forum=fake_forum, messages=fake_messages, media=fake_media,
                    notifications=fake_notifications)
    c.raw.application.config["MEDIA_ROOT"] = str(tmp_path / "media")
    c.post("/register", json={"username": "bob", "password": "s3cretpw!", "email": "b@ex.com"})
    c.post("/login", json={"username": "bob", "password": "s3cretpw!"})
    return c


def _upload(c, mime="image/png", data=_PNG, name="p.png"):
    return c.post("/media", data={"file": (io.BytesIO(data), name, mime)})


# --------------------------------------------------------------- DM refusals

@pytest.mark.parametrize("payload", [
    None, [], {},
    {"to": "bob"},                                   # body missing
    {"body": "hi"},                                  # recipient missing
    {"to": "bob", "body": ""},                       # empty body
    {"to": "bob", "body": "x" * 2001},               # body over 2000
    {"to": {"$gt": ""}, "body": "hi"},               # injection object as recipient
    {"to": "bob", "body": ["hi"]},                   # wrong body type
    {"to": "", "body": "hi"},                        # blank recipient
])
def test_dm_rejects_malformed_payloads(alice, bob, payload):
    r = alice.post("/messages", json=payload)
    assert r.status_code == 400, f"{payload!r} must be refused, got {r.status_code}"
    assert bob.get("/conversations").get_json()["conversations"] == [], "nothing may be delivered"


def test_dm_to_yourself_is_refused(alice):
    assert alice.post("/messages", json={"to": "alice", "body": "hi me"}).status_code == 400


def test_dm_to_an_unknown_user_is_404_and_undelivered(alice):
    assert alice.post("/messages", json={"to": "ghost", "body": "hello?"}).status_code == 404
    assert alice.get("/conversations").get_json()["conversations"] == []


def test_dm_spam_over_the_window_cap_is_shed_with_429(alice, bob):
    # the store-backed anti-spam window (20 per rolling 60s) — deterministic in-process, no limiter.
    for i in range(20):
        assert alice.post("/messages", json={"to": "bob", "body": f"m{i}"}).status_code == 201
    r = alice.post("/messages", json={"to": "bob", "body": "the 21st"})
    assert r.status_code == 429
    # the shed message was never delivered.
    assert len(bob.get("/conversations/alice").get_json()["messages"]) == 20


@pytest.mark.parametrize("ids", [7, "n1", {"$in": []}, [1, 2], ["ok", 3]])
def test_mark_read_rejects_non_string_list_ids(alice, ids):
    assert alice.post("/notifications/read", json={"ids": ids}).status_code == 400


def test_too_short_user_search_returns_empty_not_error(alice):
    # keystroke-driven endpoint: a 1-char query is an empty 200, never a 4xx the UI would surface.
    r = alice.get("/users/search?q=a")
    assert r.status_code == 200 and r.get_json()["results"] == []


# --------------------------------------------------------------- media upload walls

def test_upload_without_a_file_part_is_refused(alice):
    assert alice.post("/media", data={}).status_code == 400
    assert alice.post("/media", data={"wrong_part": (io.BytesIO(_PNG), "p.png", "image/png")}
                      ).status_code == 400


@pytest.mark.parametrize("mime", ["text/plain", "application/x-msdownload", "image/svg+xml",
                                  "text/html", "application/json"])
def test_upload_refuses_every_non_allowlisted_mime(alice, mime):
    # allowlist, not blocklist: html/svg (script carriers) and executables all bounce the same way.
    r = _upload(alice, mime=mime, name="evil.bin")
    assert r.status_code == 400
    assert "unsupported" in r.get_json()["error"]


def test_upload_over_the_per_file_cap_dies_with_413_before_storage(alice):
    import os
    app = alice.raw.application
    app.config["MEDIA_MAX_BYTES"] = 1024                      # shrink the wall for the test
    r = _upload(alice, data=b"\x89PNG" + b"x" * 2048)
    assert r.status_code == 413
    root = app.config["MEDIA_ROOT"]
    stored = os.listdir(root) if os.path.isdir(root) else []
    assert stored == [], "an oversize upload must die before any bytes are stored"


# --------------------------------------------------------------- media access breaches

def test_unknown_media_id_is_404(alice):
    assert alice.get("/media/deadbeef").status_code == 404


def test_a_foreign_unbound_blob_is_forbidden(alice, bob):
    mid = _upload(alice).get_json()["id"]
    assert bob.get(f"/media/{mid}").status_code == 403


def test_binding_a_foreign_blob_binds_nothing(alice, bob):
    mid = _upload(alice).get_json()["id"]
    pid = bob.post("/forum/posts", json={"title": "mine", "body": "b"}).get_json()["post"]["id"]
    assert bob.post(f"/forum/posts/{pid}/attachments", json={"attachment_ids": [mid]}
                    ).get_json()["bound"] == []
    # and the blob is STILL alice's private unbound upload.
    assert bob.get(f"/media/{mid}").status_code == 403


def test_attaching_to_a_foreign_or_missing_post_is_refused(alice, bob):
    mid = _upload(bob).get_json()["id"]
    pid = alice.post("/forum/posts", json={"title": "alice's", "body": "b"}).get_json()["post"]["id"]
    assert bob.post(f"/forum/posts/{pid}/attachments", json={"attachment_ids": [mid]}).status_code == 403
    assert bob.post("/forum/posts/nope/attachments", json={"attachment_ids": [mid]}).status_code == 404


@pytest.mark.parametrize("ids", [None, "m1", 7, [1], ["ok", 2], {"$in": []}])
def test_attach_rejects_non_string_list_ids(alice, ids):
    pid = alice.post("/forum/posts", json={"title": "t", "body": "b"}).get_json()["post"]["id"]
    assert alice.post(f"/forum/posts/{pid}/attachments",
                      json={"attachment_ids": ids} if ids is not None else {}).status_code == 400


def test_a_dm_attachment_is_dead_to_a_third_account(alice, bob, make_client, fake_users, fake_forum,
                                                    fake_messages, fake_media, fake_notifications,
                                                    tmp_path):
    mid = _upload(alice).get_json()["id"]
    alice.post("/messages/bob/attachments", json={"attachment_ids": [mid]})
    carol = make_client(fake_users, forum=fake_forum, messages=fake_messages, media=fake_media,
                        notifications=fake_notifications)
    carol.raw.application.config["MEDIA_ROOT"] = str(tmp_path / "media")
    carol.post("/register", json={"username": "carol", "password": "s3cretpw!", "email": "c@ex.com"})
    carol.post("/login", json={"username": "carol", "password": "s3cretpw!"})
    assert carol.get(f"/media/{mid}").status_code == 403
