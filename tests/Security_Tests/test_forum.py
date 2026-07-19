"""Security tests for the Forum — gated, injection-safe, graceful degradation. OWNER: Lior."""


def _login(c):
    c.post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    c.post("/login", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})


class _BrokenForum:
    def create_post(self, *a, **k):
        raise RuntimeError("down")

    def list_posts(self, before=None, limit=None):
        raise RuntimeError("down")

    def get_post(self, *a):
        raise RuntimeError("down")

    def add_comment(self, *a):
        raise RuntimeError("down")

    def list_comments(self, post_id, before=None, limit=None):
        raise RuntimeError("down")

    def vote(self, *a):
        raise RuntimeError("down")


class _PartialForum:
    """Returns a row missing `score` and `comment_count` — a partial/seed row from a real store."""

    def list_posts(self, before=None, limit=None):
        return [{"id": "1", "title": "T", "author": "alice"}]  # no score, no comment_count

    def list_comments(self, post_id, before=None, limit=None):
        return []


# (GET/POST /forum/posts auth-gating and the `{"$gt": ""}` create-injection live in
#  Negative_Tests — the same layer, same inputs, with a stronger "never stored" assertion.)


def test_invalid_vote_value_is_rejected_400(forum_client):
    _login(forum_client)
    pid = forum_client.post("/forum/posts", json={"title": "T", "body": "b"}).get_json()["post"]["id"]
    assert forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 5}).status_code == 400
    assert forum_client.post(f"/forum/posts/{pid}/vote", json={"value": True}).status_code == 400
    # a float 1.0 must NOT slip through as "1" — the contract is exactly the ints +1 / -1
    assert forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 1.0}).status_code == 400


def test_partial_store_row_does_not_crash_the_list(make_client, fake_users):
    # one malformed/partial row from the store must degrade per-row (defaults), not 500 the whole list
    c = make_client(fake_users, forum=_PartialForum())
    c.post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    c.post("/login", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    resp = c.get("/forum/posts")
    assert resp.status_code == 200
    post = resp.get_json()["posts"][0]
    assert post["score"] == 0
    assert post["comments"] == 0


def test_forum_degrades_to_503_when_store_fails(make_client, fake_users):
    c = make_client(fake_users, forum=_BrokenForum())
    c.post("/register", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    c.post("/login", json={"username": "alice", "password": "s3cretpw!", "email": "alice@example.com"})
    assert c.post("/forum/posts", json={"title": "T", "body": "b"}).status_code == 503


# (Foreign-post edit/delete -> 403 with the post left untouched is proven in Negative_Tests.
#  What stays here is the gate those 403 tests assume: an *anonymous* edit/delete never reaches
#  the ownership check at all — and PATCH/DELETE are not in the Negative auth-gate matrix.)


def test_edit_and_delete_require_login(forum_client):
    assert forum_client.patch("/forum/posts/1", json={"title": "x", "body": "y"}).status_code == 401
    assert forum_client.delete("/forum/posts/1").status_code == 401
