"""Integration tests for comment votes — Online-Forum §2.4 (up/down-votes on comments) plus the live
notification to the comment's author (§2.6). OWNER: Lior. Exercised through the HTTP surface.
"""


def _login(c, username):
    c.post("/register", json={"username": username, "password": "s3cretpw!", "email": f"{username}@example.com"})
    c.post("/login", json={"username": username, "password": "s3cretpw!"})


def _post(c, title="T", body="b"):
    return c.post("/forum/posts", json={"title": title, "body": body}).get_json()["post"]["id"]


def _comment(c, pid, body="hi"):
    return c.post(f"/forum/posts/{pid}/comments", json={"body": body}).get_json()["comment"]["id"]


def _cvote(c, pid, cid, value):
    return c.post(f"/forum/posts/{pid}/comments/{cid}/vote", json={"value": value})


def _vote_notes(c):
    return [n for n in c.get("/notifications").get_json()["notifications"] if n["type"] == "vote"]


def test_comment_vote_changes_score_one_per_user(forum_client):
    _login(forum_client, "alice")
    pid = _post(forum_client)
    cid = _comment(forum_client, pid)
    assert _cvote(forum_client, pid, cid, 1).get_json()["score"] == 1
    assert _cvote(forum_client, pid, cid, -1).get_json()["score"] == -1     # re-voting replaces
    comments = forum_client.get(f"/forum/posts/{pid}").get_json()["post"]["comments"]
    assert comments[0]["score"] == -1 and "votes" not in comments[0]        # score surfaces; tally hidden


def test_a_comment_needs_an_id_to_be_voted(forum_client):
    # the add-comment response must carry the id the vote endpoint needs
    _login(forum_client, "alice")
    pid = _post(forum_client)
    body = forum_client.post(f"/forum/posts/{pid}/comments", json={"body": "hi"}).get_json()
    assert body["comment"]["id"] and body["comment"]["score"] == 0


def test_comment_vote_notifies_the_comment_author(forum_client):
    _login(forum_client, "alice")
    pid = _post(forum_client)                       # alice owns the post
    forum_client.post("/logout")
    _login(forum_client, "bob")
    cid = _comment(forum_client, pid, "bob's take")  # bob owns the comment
    forum_client.post("/logout")
    _login(forum_client, "carol")
    assert _cvote(forum_client, pid, cid, 1).status_code == 200
    forum_client.post("/logout")
    _login(forum_client, "bob")
    notes = _vote_notes(forum_client)
    assert len(notes) == 1 and "comment" in notes[0]["text"] and "upvot" in notes[0]["text"].lower()


def test_the_post_author_is_not_notified_for_a_comment_vote(forum_client):
    # voting bob's comment must ping bob (the comment author), NOT alice (the post author)
    _login(forum_client, "alice")
    pid = _post(forum_client)
    forum_client.post("/logout")
    _login(forum_client, "bob")
    cid = _comment(forum_client, pid, "bob's take")
    forum_client.post("/logout")
    _login(forum_client, "carol")
    _cvote(forum_client, pid, cid, 1)
    forum_client.post("/logout")
    _login(forum_client, "alice")
    assert _vote_notes(forum_client) == []          # the post author gets nothing from a comment vote


def test_self_comment_vote_creates_no_notification(forum_client):
    _login(forum_client, "bob")
    pid = _post(forum_client)
    cid = _comment(forum_client, pid)
    _cvote(forum_client, pid, cid, 1)
    assert _vote_notes(forum_client) == []


def test_comment_vote_on_missing_comment_is_404(forum_client):
    _login(forum_client, "alice")
    pid = _post(forum_client)
    assert _cvote(forum_client, pid, "no-such-comment", 1).status_code == 404


def test_comment_vote_rejects_bad_value(forum_client):
    _login(forum_client, "alice")
    pid = _post(forum_client)
    cid = _comment(forum_client, pid)
    assert _cvote(forum_client, pid, cid, 2).status_code == 400
    assert _cvote(forum_client, pid, cid, True).status_code == 400   # a bool is not an accepted int


def test_comment_vote_requires_login(forum_client):
    # not logged in -> the auth gate rejects (the wrapper still supplies the CSRF token)
    assert forum_client.post("/forum/posts/p/comments/c/vote", json={"value": 1}).status_code == 401


def test_post_and_comment_votes_notify_independently(forum_client):
    # a voter hitting BOTH a post and a comment by the same author -> two distinct pings (refs differ,
    # so the comment vote is NOT coalesced away by the post vote)
    _login(forum_client, "alice")
    pid = _post(forum_client)
    cid = _comment(forum_client, pid)               # alice authors both the post and the comment
    forum_client.post("/logout")
    _login(forum_client, "carol")
    forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 1})
    _cvote(forum_client, pid, cid, 1)
    forum_client.post("/logout")
    _login(forum_client, "alice")
    notes = _vote_notes(forum_client)
    texts = " ".join(n["text"] for n in notes)
    assert len(notes) == 2 and "your post" in texts and "your comment" in texts
