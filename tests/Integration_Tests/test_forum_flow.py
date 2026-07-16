"""Integration tests for the Forum CRUD (posts / comments / votes). OWNER: Lior."""


def _login(c, username="alice"):
    c.post("/register", json={"username": username, "password": "s3cretpw!", "email": f"{username}@example.com"})
    c.post("/login", json={"username": username, "password": "s3cretpw!"})


def _new_post(c, title="First", body="hello"):
    return c.post("/forum/posts", json={"title": title, "body": body})


def test_create_then_list_posts(forum_client):
    _login(forum_client)
    assert _new_post(forum_client).status_code == 201
    posts = forum_client.get("/forum/posts").get_json()["posts"]
    assert len(posts) == 1
    assert posts[0]["title"] == "First"
    assert posts[0]["author"] == "alice"
    assert posts[0]["score"] == 0


def test_forum_feed_read_is_bounded_newest_first(forum_client, fake_forum):
    # Robustness / DoS-amplification guard: the feed read is CAPPED (newest-first), so a post-flood can't make
    # every /forum/posts read unboundedly slow for everyone. list_cap mirrors db.FORUM_LIST_MAX (200),
    # lowered here to keep the test small. Behaviour-neutral below the cap (all posts returned).
    fake_forum.list_cap = 3
    _login(forum_client)
    for i in range(6):
        assert _new_post(forum_client, f"p{i}", "b").status_code == 201
    posts = forum_client.get("/forum/posts").get_json()["posts"]
    assert len(posts) == 3                                      # capped, not all 6
    assert [p["title"] for p in posts] == ["p5", "p4", "p3"]    # the newest 3, newest first


def test_list_posts_carry_created_at_in_creation_order(forum_client):
    # The client sorts the forum by created_at (newest-first by default) and renders each post's age, so the
    # summary must expose a positive, strictly-increasing created_at per creation order.
    _login(forum_client)
    _new_post(forum_client, "one", "a")
    _new_post(forum_client, "two", "b")
    posts = {p["title"]: p for p in forum_client.get("/forum/posts").get_json()["posts"]}
    assert posts["one"]["created_at"] > 0 and posts["two"]["created_at"] > 0
    assert posts["two"]["created_at"] > posts["one"]["created_at"]   # the later post is strictly newer


def test_get_post_with_its_comments(forum_client):
    _login(forum_client)
    pid = _new_post(forum_client, "T", "b").get_json()["post"]["id"]
    forum_client.post(f"/forum/posts/{pid}/comments", json={"body": "great"})
    post = forum_client.get(f"/forum/posts/{pid}").get_json()["post"]
    assert post["body"] == "b"
    assert len(post["comments"]) == 1
    assert post["comments"][0]["body"] == "great"


def test_vote_changes_score_and_one_vote_per_user(forum_client):
    _login(forum_client)
    pid = _new_post(forum_client, "T", "b").get_json()["post"]["id"]
    assert forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 1}).get_json()["score"] == 1
    # re-voting replaces the previous vote (not additive)
    assert forum_client.post(f"/forum/posts/{pid}/vote", json={"value": -1}).get_json()["score"] == -1


def test_anonymous_post_hides_the_author(forum_client):
    _login(forum_client)
    forum_client.post("/forum/posts", json={"title": "T", "body": "b", "anonymous": True})
    assert forum_client.get("/forum/posts").get_json()["posts"][0]["author"] == "Anonymous"


def test_comment_on_missing_post_is_404(forum_client):
    _login(forum_client)
    assert forum_client.post("/forum/posts/999/comments", json={"body": "x"}).status_code == 404


def test_get_missing_post_is_404(forum_client):
    _login(forum_client)
    assert forum_client.get("/forum/posts/999").status_code == 404


def test_author_can_edit_their_post(forum_client):
    _login(forum_client)
    pid = _new_post(forum_client, "Old", "old body").get_json()["post"]["id"]
    resp = forum_client.patch(f"/forum/posts/{pid}", json={"title": "New", "body": "new body"})
    assert resp.status_code == 200
    assert resp.get_json()["post"]["title"] == "New"
    assert forum_client.get(f"/forum/posts/{pid}").get_json()["post"]["body"] == "new body"


def test_author_can_delete_their_post(forum_client):
    _login(forum_client)
    pid = _new_post(forum_client).get_json()["post"]["id"]
    assert forum_client.delete(f"/forum/posts/{pid}").status_code == 200
    assert forum_client.get(f"/forum/posts/{pid}").status_code == 404  # gone
    assert forum_client.get("/forum/posts").get_json()["posts"] == []


def test_edit_missing_post_is_404(forum_client):
    _login(forum_client)
    assert forum_client.patch("/forum/posts/999", json={"title": "X", "body": "y"}).status_code == 404


def test_edit_rejects_bad_body_400(forum_client):
    _login(forum_client)
    pid = _new_post(forum_client).get_json()["post"]["id"]
    assert forum_client.patch(f"/forum/posts/{pid}", json={"title": "", "body": "y"}).status_code == 400


def test_votes_aggregate_across_users(forum_client):
    # one vote per user, but DISTINCT users' votes sum into the score (not last-write-wins)
    _login(forum_client, "alice")
    pid = _new_post(forum_client).get_json()["post"]["id"]
    assert forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 1}).get_json()["score"] == 1
    forum_client.post("/logout")
    _login(forum_client, "bob")
    assert forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 1}).get_json()["score"] == 2
