"""Integration tests for the received-engagement metric (`GET /me/engagement`) — OWNER: Elad.

GUIDELINES §3.3: like/dislike "with visible counts and a per-user total in a personal area". The
route answers the logged-in user's own totals — votes OTHERS cast on their posts and comments —
and never says who voted (the raw voter list stays in the store, like the forum's score fields).
"""


def _login(c, username="alice"):
    c.post("/register", json={"username": username, "password": "s3cretpw!", "email": f"{username}@example.com"})
    c.post("/login", json={"username": username, "password": "s3cretpw!"})


def _switch(c, username):
    c.post("/logout")
    _login(c, username)


def test_engagement_requires_login(forum_client):
    assert forum_client.get("/me/engagement").status_code == 401


def test_engagement_starts_at_zero(forum_client):
    _login(forum_client)
    body = forum_client.get("/me/engagement").get_json()
    assert body == {"up": 0, "down": 0, "score": 0}


def test_votes_received_on_posts_and_comments_aggregate(forum_client):
    _login(forum_client, "alice")
    pid = forum_client.post("/forum/posts", json={"title": "T", "body": "b"}).get_json()["post"]["id"]
    cid = forum_client.post(f"/forum/posts/{pid}/comments", json={"body": "mine too"}).get_json()["comment"]["id"]

    _switch(forum_client, "bob")
    forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 1})
    forum_client.post(f"/forum/posts/{pid}/comments/{cid}/vote", json={"value": 1})
    _switch(forum_client, "carol")
    forum_client.post(f"/forum/posts/{pid}/vote", json={"value": -1})

    _switch(forum_client, "alice")
    assert forum_client.get("/me/engagement").get_json() == {"up": 2, "down": 1, "score": 1}


def test_own_vote_on_own_post_is_not_received_engagement(forum_client):
    _login(forum_client, "alice")
    pid = forum_client.post("/forum/posts", json={"title": "T", "body": "b"}).get_json()["post"]["id"]
    forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 1})
    assert forum_client.get("/me/engagement").get_json() == {"up": 0, "down": 0, "score": 0}


def test_anonymous_posts_still_feed_their_authors_metric(forum_client):
    _login(forum_client, "alice")
    pid = forum_client.post("/forum/posts", json={"title": "T", "body": "b", "anonymous": True}).get_json()["post"]["id"]
    _switch(forum_client, "bob")
    forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 1})
    _switch(forum_client, "alice")
    assert forum_client.get("/me/engagement").get_json()["up"] == 1


def test_the_response_never_names_the_voters(forum_client):
    """The metric is counts only — exposing voter identities would leak what the forum's public
    shapes deliberately withhold (votes are stored, never returned)."""
    _login(forum_client, "alice")
    pid = forum_client.post("/forum/posts", json={"title": "T", "body": "b"}).get_json()["post"]["id"]
    _switch(forum_client, "bob")
    forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 1})
    _switch(forum_client, "alice")
    body = forum_client.get("/me/engagement").get_json()
    assert set(body) == {"up", "down", "score"}
    assert "bob" not in str(body)


def test_re_voting_replaces_in_the_metric_too(forum_client):
    """A user flipping their vote must move the tally, not double-count."""
    _login(forum_client, "alice")
    pid = forum_client.post("/forum/posts", json={"title": "T", "body": "b"}).get_json()["post"]["id"]
    _switch(forum_client, "bob")
    forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 1})
    forum_client.post(f"/forum/posts/{pid}/vote", json={"value": -1})
    _switch(forum_client, "alice")
    assert forum_client.get("/me/engagement").get_json() == {"up": 0, "down": 1, "score": -1}
