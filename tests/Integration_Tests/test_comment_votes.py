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
    """A comment vote moves its score and voting again replaces the previous vote, and the thread read-back shows the score while keeping the voter identities to itself."""
    _login(forum_client, "alice")
    pid = _post(forum_client)
    cid = _comment(forum_client, pid)
    assert _cvote(forum_client, pid, cid, 1).get_json()["score"] == 1
    assert _cvote(forum_client, pid, cid, -1).get_json()["score"] == -1     # re-voting replaces
    comments = forum_client.get(f"/forum/posts/{pid}/comments").get_json()["comments"]   # #331: own endpoint
    assert comments[0]["score"] == -1 and "votes" not in comments[0]        # score surfaces; tally hidden


def test_a_comment_needs_an_id_to_be_voted(forum_client):
    """The response to posting a comment carries the id the vote endpoint needs, so a reader can vote on a comment they just made without reloading the thread to find it."""
    _login(forum_client, "alice")
    pid = _post(forum_client)
    body = forum_client.post(f"/forum/posts/{pid}/comments", json={"body": "hi"}).get_json()
    assert body["comment"]["id"] and body["comment"]["score"] == 0


def test_comment_vote_notifies_the_comment_author(forum_client):
    """Voting on a comment pings the person who wrote it, which is the whole point of the notification — recognition reaching the right person."""
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
    """A vote on a comment notifies the COMMENT's author, not the post's — otherwise anyone with a busy thread is buried in alerts about other people's replies."""
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
    """Voting on your own comment notifies nobody, so the feed is not filled with alerts about your own actions."""
    _login(forum_client, "bob")
    pid = _post(forum_client)
    cid = _comment(forum_client, pid)
    _cvote(forum_client, pid, cid, 1)
    assert _vote_notes(forum_client) == []


def test_comment_vote_on_missing_comment_is_404(forum_client):
    """Voting on a comment that does not exist is a 404, so a stale thread on screen cannot create a score against nothing."""
    _login(forum_client, "alice")
    pid = _post(forum_client)
    assert _cvote(forum_client, pid, "no-such-comment", 1).status_code == 404


def test_comment_vote_rejects_bad_value(forum_client):
    """Only the two real vote values are accepted — an out-of-range number is refused, and so is a bool, which would otherwise pass as the integer 1."""
    _login(forum_client, "alice")
    pid = _post(forum_client)
    cid = _comment(forum_client, pid)
    assert _cvote(forum_client, pid, cid, 2).status_code == 400
    assert _cvote(forum_client, pid, cid, True).status_code == 400   # a bool is not an accepted int


def test_comment_vote_requires_login(forum_client):
    """Voting requires an account, since one-vote-per-person is meaningless for an anonymous caller."""
    assert forum_client.post("/forum/posts/p/comments/c/vote", json={"value": 1}).status_code == 401


def test_post_and_comment_votes_notify_independently(forum_client):
    """One voter reaching both a post and a comment by the same author produces TWO distinct alerts.

    The two must not be coalesced, or the author learns about only one of them.
    """
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


def test_comment_vote_response_carries_the_tallies_for_an_in_place_repaint(forum_client):
    """The client repaints just the voted row rather than reloading the thread — which would throw away pages the reader already scrolled through — so the vote reply must carry the same tallies that row renders.

    A score-only reply would leave the like and dislike counts visibly stale, and the read-back here confirms the reply told the truth.
    """
    _login(forum_client, "alice")
    pid = _post(forum_client)
    cid = _comment(forum_client, pid)
    assert _cvote(forum_client, pid, cid, 1).get_json() == {"score": 1, "likes": 1, "dislikes": 0}
    assert _cvote(forum_client, pid, cid, -1).get_json() == {"score": -1, "likes": 0, "dislikes": 1}
    # and the thread read-back agrees with what the vote reply claimed
    comment = forum_client.get(f"/forum/posts/{pid}/comments").get_json()["comments"][0]
    assert (comment["likes"], comment["dislikes"]) == (0, 1)
