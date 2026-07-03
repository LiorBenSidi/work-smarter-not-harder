"""Account deletion — GDPR right to erasure (DELETE /account). OWNER: Lior.

The cascade removes the user's identity AND all their personal data across every store, while leaving
the forum consistent for everyone else (their comments/votes are stripped and scores recomputed).
Password-gated, auth-gated, CSRF-protected. Runs on the in-memory fakes (no Mongo).
"""
import pytest


@pytest.fixture
def full_client(make_client, fake_users, fake_profiles, fake_history, fake_forum, fake_messages,
                fake_notifications):
    """A client wired with EVERY store, so the whole deletion cascade runs end-to-end. The individual
    fake_* fixtures resolve to the same instances, so a test can inspect them directly after the call."""
    return make_client(fake_users, profiles=fake_profiles, history=fake_history, forum=fake_forum,
                       messages=fake_messages, notifications=fake_notifications)


def _register_login(client, name, pw="password123"):
    client.post("/register", json={"username": name, "password": pw, "email": f"{name}@ex.com"})
    r = client.post("/login", json={"username": name, "password": pw})
    assert r.status_code == 200
    return r.get_json()["username"]


def test_delete_account_cascades_across_every_store(full_client, fake_users, fake_profiles, fake_history,
                                                    fake_forum, fake_messages, fake_notifications):
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
    assert all(c["author"] != "alice" for c in posts[bob_post["id"]]["comments"])
    assert "alice" not in posts[bob_post["id"]]["votes"]
    assert posts[bob_post["id"]]["score"] == 0                       # her +1 removed
    # every DM (both directions) + notifications (inbox AND the one where she was the actor) erased
    assert fake_messages.list_conversation("alice", "bob") == []
    assert fake_notifications.list("alice") == []
    assert fake_notifications.list("bob") == []


def test_delete_preserves_other_users_forum_content(full_client, fake_forum):
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
    assert [c["author"] for c in post["comments"]] == ["bob"]        # only bob's comment remains
    assert post["score"] == 1                                        # alice's +1 removed, bob's kept


def test_delete_requires_the_password(full_client, fake_users):
    _register_login(full_client, "alice")
    r = full_client.delete("/account", json={})
    assert r.status_code == 400
    assert fake_users.get("alice") is not None                      # not deleted


def test_delete_rejects_wrong_password(full_client, fake_users):
    _register_login(full_client, "alice", pw="password123")
    r = full_client.delete("/account", json={"password": "WRONGpass1"})
    assert r.status_code == 403
    assert fake_users.get("alice") is not None                      # NOT deleted


def test_delete_rejects_non_string_password_injection(full_client, fake_users):
    _register_login(full_client, "alice")
    r = full_client.delete("/account", json={"password": {"$ne": ""}})
    assert r.status_code == 400
    assert fake_users.get("alice") is not None


def test_delete_requires_authentication(full_client):
    r = full_client.delete("/account", json={"password": "password123"})
    assert r.status_code == 401


def test_delete_ends_the_session(full_client):
    _register_login(full_client, "alice")
    assert full_client.get("/me").status_code == 200
    full_client.delete("/account", json={"password": "password123"})
    assert full_client.get("/me").status_code == 401                # session cleared
