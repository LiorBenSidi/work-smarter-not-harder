"""Security tests for the Forum — gated, injection-safe, graceful degradation. OWNER: Lior."""


def _login(c):
    c.post("/register", json={"username": "alice", "password": "s3cretpw!"})
    c.post("/login", json={"username": "alice", "password": "s3cretpw!"})


class _BrokenForum:
    def create_post(self, *a, **k):
        raise RuntimeError("down")

    def list_posts(self):
        raise RuntimeError("down")

    def get_post(self, *a):
        raise RuntimeError("down")

    def add_comment(self, *a):
        raise RuntimeError("down")

    def vote(self, *a):
        raise RuntimeError("down")


def test_forum_list_requires_login(forum_client):
    assert forum_client.get("/forum/posts").status_code == 401


def test_forum_create_requires_login(forum_client):
    assert forum_client.post("/forum/posts", json={"title": "T", "body": "b"}).status_code == 401


def test_injection_in_post_is_rejected_400(forum_client):
    _login(forum_client)
    assert forum_client.post("/forum/posts", json={"title": {"$gt": ""}, "body": "b"}).status_code == 400


def test_invalid_vote_value_is_rejected_400(forum_client):
    _login(forum_client)
    pid = forum_client.post("/forum/posts", json={"title": "T", "body": "b"}).get_json()["post"]["id"]
    assert forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 5}).status_code == 400
    assert forum_client.post(f"/forum/posts/{pid}/vote", json={"value": True}).status_code == 400


def test_forum_degrades_to_503_when_store_fails(make_client, fake_users):
    c = make_client(fake_users, forum=_BrokenForum())
    c.post("/register", json={"username": "alice", "password": "s3cretpw!"})
    c.post("/login", json={"username": "alice", "password": "s3cretpw!"})
    assert c.post("/forum/posts", json={"title": "T", "body": "b"}).status_code == 503
