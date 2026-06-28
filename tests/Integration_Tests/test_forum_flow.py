"""Integration tests for the Forum CRUD (posts / comments / votes). OWNER: Lior."""


def _login(c, username="alice"):
    c.post("/register", json={"username": username, "password": "s3cretpw!"})
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
