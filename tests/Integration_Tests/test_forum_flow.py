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


def test_list_posts_carry_created_at_in_creation_order(forum_client):
    # The client sorts the forum by created_at (newest-first by default) and renders each post's age, so the
    # summary must expose a positive, strictly-increasing created_at per creation order.
    _login(forum_client)
    _new_post(forum_client, "one", "a")
    _new_post(forum_client, "two", "b")
    posts = {p["title"]: p for p in forum_client.get("/forum/posts").get_json()["posts"]}
    assert posts["one"]["created_at"] > 0 and posts["two"]["created_at"] > 0
    assert posts["two"]["created_at"] > posts["one"]["created_at"]   # the later post is strictly newer


def test_forum_feed_pages_back_to_the_oldest_via_next_before(forum_client):
    # #325: the feed is a bounded page + a `next_before` cursor. Walking the cursor must reach EVERY post,
    # newest-first, exactly once — so a user reads even the oldest post without any unbounded read.
    _login(forum_client)
    for i in range(5):
        _new_post(forum_client, f"p{i}", "b")
    seen, before = [], None
    for _ in range(10):                                   # bounded loop guard (5 posts / 2 per page = 3 pages)
        url = "/forum/posts?limit=2" + (f"&before={before}" if before is not None else "")
        data = forum_client.get(url).get_json()
        seen += [p["title"] for p in data["posts"]]
        before = data["next_before"]
        if before is None:
            break
    assert seen == ["p4", "p3", "p2", "p1", "p0"]         # full newest-first walk, each post exactly once


def test_forum_feed_last_page_has_no_next_cursor(forum_client):
    # A page that isn't full means nothing older remains -> next_before is null, so the client stops paging.
    _login(forum_client)
    _new_post(forum_client, "only", "b")
    data = forum_client.get("/forum/posts?limit=5").get_json()
    assert len(data["posts"]) == 1
    assert data["next_before"] is None


def test_forum_feed_ignores_a_garbage_before_cursor(forum_client):
    # A non-numeric cursor must fall back to the newest page — never a 500, never an unbounded scan.
    _login(forum_client)
    _new_post(forum_client, "hi", "b")
    resp = forum_client.get("/forum/posts?before=not-a-number")
    assert resp.status_code == 200
    assert [p["title"] for p in resp.get_json()["posts"]] == ["hi"]


def test_get_post_with_its_comments(forum_client):
    # #331: comments are NOT embedded in the post detail — the detail carries a count, and the comments
    # themselves are fetched from the paginated GET /forum/posts/<id>/comments endpoint.
    _login(forum_client)
    pid = _new_post(forum_client, "T", "b").get_json()["post"]["id"]
    forum_client.post(f"/forum/posts/{pid}/comments", json={"body": "great"})
    post = forum_client.get(f"/forum/posts/{pid}").get_json()["post"]
    assert post["body"] == "b"
    assert post["comment_count"] == 1 and "comments" not in post
    data = forum_client.get(f"/forum/posts/{pid}/comments").get_json()
    assert data["next_before"] is None
    assert [c["body"] for c in data["comments"]] == ["great"]


def test_comments_endpoint_pages_back_to_the_oldest_via_next_before(forum_client):
    # #331: the comments read is a bounded page + a `next_before` cursor (mirrors the forum feed). Walking
    # the cursor must reach EVERY comment, newest-first, exactly once — even the oldest, with no unbounded read.
    _login(forum_client)
    pid = _new_post(forum_client, "T", "b").get_json()["post"]["id"]
    for i in range(5):
        forum_client.post(f"/forum/posts/{pid}/comments", json={"body": f"c{i}"})
    seen, before = [], None
    for _ in range(10):                                   # bounded loop guard (5 comments / 2 per page)
        url = f"/forum/posts/{pid}/comments?limit=2" + (f"&before={before}" if before is not None else "")
        data = forum_client.get(url).get_json()
        seen += [c["body"] for c in data["comments"]]
        before = data["next_before"]
        if before is None:
            break
    assert seen == ["c4", "c3", "c2", "c1", "c0"]         # full newest-first walk, each comment exactly once


def test_comments_endpoint_ignores_a_garbage_before_cursor(forum_client):
    _login(forum_client)
    pid = _new_post(forum_client, "T", "b").get_json()["post"]["id"]
    forum_client.post(f"/forum/posts/{pid}/comments", json={"body": "hi"})
    resp = forum_client.get(f"/forum/posts/{pid}/comments?before=not-a-number")
    assert resp.status_code == 200
    assert [c["body"] for c in resp.get_json()["comments"]] == ["hi"]


def test_comments_endpoint_requires_login(forum_client):
    assert forum_client.get("/forum/posts/whatever/comments").status_code == 401


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


# (The empty-title PATCH wall is proven in Negative_Tests with the same input, alongside the
#  over-length wall and a "the refusal changed nothing" assertion. test_edit_missing_post_is_404
#  above stays: PATCH is absent from that file's unknown-post sweep.)


def test_votes_aggregate_across_users(forum_client):
    # one vote per user, but DISTINCT users' votes sum into the score (not last-write-wins)
    _login(forum_client, "alice")
    pid = _new_post(forum_client).get_json()["post"]["id"]
    assert forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 1}).get_json()["score"] == 1
    forum_client.post("/logout")
    _login(forum_client, "bob")
    assert forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 1}).get_json()["score"] == 2
