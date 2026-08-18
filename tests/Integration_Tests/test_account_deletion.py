"""Account deletion — GDPR right to erasure (DELETE /account). OWNER: Lior.

The cascade removes the user's identity AND all their personal data across every store, while leaving
the forum consistent for everyone else (their comments/votes are stripped and scores recomputed).
Password-gated, auth-gated, CSRF-protected. Runs on the in-memory fakes (no Mongo).
"""
import io

import pytest


@pytest.fixture
def full_client(make_client, fake_users, fake_profiles, fake_history, fake_forum, fake_messages,
                fake_notifications, fake_media, tmp_path):
    """A client wired with EVERY store, so the whole deletion cascade runs end-to-end. The individual
    fake_* fixtures resolve to the same instances, so a test can inspect them directly after the call.

    Media is injected too (#507): the cascade now erases uploads, so without a fake the purge would try
    to resolve Mongo — the same reason `forum_client` injects notifications. MEDIA_ROOT points at a
    throwaway pytest tmp dir so a test can assert on real files without touching the /app/media volume.
    """
    c = make_client(fake_users, profiles=fake_profiles, history=fake_history, forum=fake_forum,
                    messages=fake_messages, notifications=fake_notifications, media=fake_media)
    c.raw.application.config["MEDIA_ROOT"] = str(tmp_path / "media")
    return c


def _register_login(client, name, pw="password123"):
    client.post("/register", json={"username": name, "password": pw, "email": f"{name}@ex.com"})
    r = client.post("/login", json={"username": name, "password": pw})
    assert r.status_code == 200
    return r.get_json()["username"]


def test_delete_account_cascades_across_every_store(full_client, fake_users, fake_profiles, fake_history,
                                                    fake_forum, fake_messages, fake_notifications):
    """Erasure reaches EVERY store the user touched — identity, profile, history, their posts and comments, their votes, both directions of their messages, and notifications where they were merely the actor.

    A cascade that misses one collection leaves personal data behind after the user was told it was gone.
    """
    _register_login(full_client, "alice")
    # alice creates data in every collection
    fake_profiles.save("alice", {"age": 30, "goal": "maintain"})
    fake_history.add("alice", {"timestamp": "2026-07-01", "assessment": "Ready", "calories": 2000})
    alice_post = fake_forum.create_post("alice", "Alice's post", "hello", False)
    bob_post = fake_forum.create_post("bob", "Bob's post", "hi", False)
    fake_forum.add_comment(bob_post["id"], "alice", "nice post")     # alice's comment on bob's post
    fake_forum.vote(bob_post["id"], "alice", 1)                      # alice's vote on bob's post
    fake_messages.send("alice", "bob", "hey bob")
    fake_messages.send("bob", "alice", "hi alice")
    fake_notifications.add("alice", "dm", "bob", None, "Bob messaged you")      # alice's inbox
    fake_notifications.add("bob", "vote", "alice", None, "alice upvoted your post")  # alice as ACTOR

    r = full_client.delete("/account", json={"password": "password123"})
    assert r.status_code == 200 and r.get_json()["status"] == "account deleted"

    # identity + profile + history erased
    assert fake_users.get("alice") is None
    assert fake_profiles.get("alice") is None
    assert fake_history.list("alice") == []
    # alice's own post is gone; bob's post remains with her comment + vote stripped and score recomputed
    posts = {p["id"]: p for p in fake_forum.list_posts()}
    assert alice_post["id"] not in posts
    assert bob_post["id"] in posts
    # her comment on bob's post is stripped from the comments collection (#331)
    assert all(c["author"] != "alice" for c in fake_forum.list_comments(bob_post["id"]))
    assert "alice" not in posts[bob_post["id"]]["votes"]
    assert posts[bob_post["id"]]["score"] == 0                       # her +1 removed
    # every DM (both directions) + notifications (inbox AND the one where she was the actor) erased
    assert fake_messages.list_conversation("alice", "bob") == []
    assert fake_notifications.list("alice") == []
    assert fake_notifications.list("bob") == []


def test_delete_preserves_other_users_forum_content(full_client, fake_forum):
    """One person leaving must not damage everyone else's forum: another author's post survives with their own comment and vote intact, and only the departing user's contributions are removed and the score recomputed."""
    _register_login(full_client, "alice")
    bp = fake_forum.create_post("bob", "keep me", "body", False)
    fake_forum.add_comment(bp["id"], "bob", "bob comment")
    fake_forum.add_comment(bp["id"], "alice", "alice comment")
    fake_forum.vote(bp["id"], "bob", 1)
    fake_forum.vote(bp["id"], "alice", 1)
    assert fake_forum.get_post(bp["id"])["score"] == 2

    full_client.delete("/account", json={"password": "password123"})

    post = fake_forum.get_post(bp["id"])
    assert post is not None                                          # bob's post survives
    assert [c["author"] for c in fake_forum.list_comments(bp["id"])] == ["bob"]   # only bob's comment remains (#331)
    assert post["score"] == 1                                        # alice's +1 removed, bob's kept


def test_delete_requires_the_password(full_client, fake_users):
    """Erasure is irreversible, so it demands the password — and an attempt without one leaves the account fully intact."""
    _register_login(full_client, "alice")
    r = full_client.delete("/account", json={})
    assert r.status_code == 400
    assert fake_users.get("alice") is not None                      # not deleted


def test_delete_rejects_wrong_password(full_client, fake_users):
    """A wrong password does not delete the account, so someone at an unattended screen cannot destroy it on a guess."""
    _register_login(full_client, "alice", pw="password123")
    r = full_client.delete("/account", json={"password": "WRONGpass1"})
    assert r.status_code == 403
    assert fake_users.get("alice") is not None                      # NOT deleted


def test_delete_rejects_non_string_password_injection(full_client, fake_users):
    """An operator object sent as the password is refused, so the confirmation step cannot be turned into a query that matches anything."""
    _register_login(full_client, "alice")
    r = full_client.delete("/account", json={"password": {"$ne": ""}})
    assert r.status_code == 400
    assert fake_users.get("alice") is not None


def test_delete_requires_authentication(full_client):
    """An anonymous caller cannot delete an account at all, whatever password they supply."""
    r = full_client.delete("/account", json={"password": "password123"})
    assert r.status_code == 401


def test_delete_ends_the_session_and_drops_the_remember_cookie(full_client):
    """Deletion clears BOTH pieces of state the browser is holding — the session and the "remember this
    browser" cookie — so nothing about the deleted account is left behind on the machine.

    The session half was already covered. The cookie half was not: measured, removing the
    delete_cookie call left the whole suite green (measured). Its twin on the password-change route
    IS covered (test_change_password_clears_this_browsers_remember_cookie), so this was an asymmetry
    rather than a deliberate omission.
    """
    _register_login(full_client, "alice")
    assert full_client.get("/me").status_code == 200
    resp = full_client.delete("/account", json={"password": "password123"})
    assert full_client.get("/me").status_code == 401                # session cleared
    assert "remember_token=;" in resp.headers.get("Set-Cookie", "") or \
           "remember_token=\"\"" in resp.headers.get("Set-Cookie", ""), \
        f"deletion must expire the remember cookie, got {resp.headers.get('Set-Cookie')!r}"


def _upload(client, name="shot.png", mime="image/png", data=b"\x89PNG\r\n\x1a\n"):
    """Upload one blob through the real route, so the file lands on MEDIA_ROOT the way production writes it."""
    r = client.post("/media", data={"file": (io.BytesIO(data), name, mime)},
                    content_type="multipart/form-data")
    assert r.status_code == 201, r.get_data(as_text=True)
    return r.get_json()["id"]


def test_delete_account_erases_uploaded_media_documents_and_files(full_client, fake_media, tmp_path):
    """#507: media was the ONE store that outlived a deleted account.

    Reproduced on production before the fix — every other store went to zero while `media` stayed at
    25 documents and 25 files on disk, leaving blobs owned by a username that no longer existed. Both
    halves have to go: a document with no account is an orphan, and a file with no document is
    unreachable storage nobody can account for.
    """
    _register_login(full_client, "alice")
    media_id = _upload(full_client)
    blob = tmp_path / "media" / f"{media_id}.png"
    assert blob.exists()                                   # precondition: the bytes really are on disk
    assert fake_media.get(media_id) is not None

    r = full_client.delete("/account", json={"password": "password123"})
    assert r.status_code == 200

    assert fake_media.get(media_id) is None, "the media document survived account deletion"
    assert not blob.exists(), "the uploaded file survived account deletion"


def test_deleting_one_account_leaves_another_users_media_alone(full_client, make_client, fake_users,
                                                               fake_media, tmp_path):
    """Erasure is owner-scoped. A cascade that purged by anything broader would delete bystanders'
    uploads — a far worse failure than the one #507 reported."""
    bob = make_client(fake_users, media=fake_media)
    bob.raw.application.config["MEDIA_ROOT"] = str(tmp_path / "media")
    _register_login(bob, "bob")
    bob_media = _upload(bob)

    _register_login(full_client, "alice")
    alice_media = _upload(full_client)

    full_client.delete("/account", json={"password": "password123"})

    assert fake_media.get(alice_media) is None
    assert fake_media.get(bob_media) is not None, "bob's upload was erased with alice's account"
    assert (tmp_path / "media" / f"{bob_media}.png").exists()
