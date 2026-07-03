"""Integration tests for vote notifications — Online-Forum §2.6 (a live notification to a post's
author when someone up/downvotes it). OWNER: Lior.

Behaviour under test (all through the HTTP surface, not internals): the author is notified, a self-vote
is not, the voter and uninvolved users are not, a downvote reads as a downvote, distinct voters each
notify once, re-votes are coalesced while unread (anti-spam §2.7), and a broken notification store must
never fail the vote itself (best-effort).
"""


def _login(c, username):
    c.post("/register", json={"username": username, "password": "s3cretpw!", "email": f"{username}@example.com"})
    c.post("/login", json={"username": username, "password": "s3cretpw!"})


def _post_as(c, username, title="T", body="b"):
    """Register+login `username`, create a post, log back out; return the post id."""
    _login(c, username)
    pid = c.post("/forum/posts", json={"title": title, "body": body}).get_json()["post"]["id"]
    c.post("/logout")
    return pid


def _vote(c, pid, value):
    return c.post(f"/forum/posts/{pid}/vote", json={"value": value})


def _vote_as(c, username, pid, value):
    """Register+login `username`, cast one vote on `pid`, then log back out."""
    _login(c, username)
    _vote(c, pid, value)
    c.post("/logout")


def _vote_notes(c, unread_only=False):
    data = c.get("/notifications").get_json()
    return [n for n in data["notifications"] if n["type"] == "vote" and (not unread_only or not n["read"])]


def test_upvote_notifies_the_post_author(forum_client):
    pid = _post_as(forum_client, "bob")
    _login(forum_client, "alice")
    assert _vote(forum_client, pid, 1).status_code == 200
    forum_client.post("/logout")
    _login(forum_client, "bob")
    notes = _vote_notes(forum_client)
    assert len(notes) == 1
    assert "upvot" in notes[0]["text"].lower()
    assert forum_client.get("/notifications").get_json()["unread"] >= 1


def test_self_vote_creates_no_notification(forum_client):
    _login(forum_client, "bob")
    pid = forum_client.post("/forum/posts", json={"title": "T", "body": "b"}).get_json()["post"]["id"]
    assert _vote(forum_client, pid, 1).status_code == 200
    assert _vote_notes(forum_client) == []          # you don't get pinged for voting your own post


def test_downvote_notification_reads_as_a_downvote(forum_client):
    pid = _post_as(forum_client, "bob")
    _login(forum_client, "alice")
    _vote(forum_client, pid, -1)
    forum_client.post("/logout")
    _login(forum_client, "bob")
    notes = _vote_notes(forum_client)
    assert len(notes) == 1 and "downvot" in notes[0]["text"].lower()


def test_the_voter_is_not_notified(forum_client):
    pid = _post_as(forum_client, "bob")
    _login(forum_client, "alice")
    _vote(forum_client, pid, 1)
    assert _vote_notes(forum_client) == []          # alice (the voter) has no vote notification of her own


def test_an_uninvolved_user_sees_no_vote_notification(forum_client):
    pid = _post_as(forum_client, "bob")
    _vote_as(forum_client, "alice", pid, 1)
    _login(forum_client, "carol")                   # carol never touched this post
    assert _vote_notes(forum_client) == []          # notifications are strictly per-recipient


def test_distinct_voters_each_notify_once(forum_client):
    pid = _post_as(forum_client, "bob")
    _vote_as(forum_client, "alice", pid, 1)
    _vote_as(forum_client, "carol", pid, 1)
    _login(forum_client, "bob")
    assert len(_vote_notes(forum_client)) == 2       # one ping per distinct voter


def test_rapid_revotes_are_coalesced(forum_client):
    # anti-spam (§2.7): a voter flipping their vote in quick succession must not flood the author —
    # the three votes land inside the coalesce window, so they collapse to a single ping
    pid = _post_as(forum_client, "bob")
    _login(forum_client, "alice")
    _vote(forum_client, pid, 1)
    _vote(forum_client, pid, -1)
    _vote(forum_client, pid, 1)
    forum_client.post("/logout")
    _login(forum_client, "bob")
    assert len(_vote_notes(forum_client, unread_only=True)) == 1   # coalesced to one ping


def test_a_vote_past_the_coalesce_window_pings_again(make_client, fake_users, fake_forum, fake_notifications):
    # coalescing is time-bounded, never a permanent mute: a genuinely later vote (past the window)
    # pings again. We reach into the fake store to backdate the first ping instead of sleeping 60s.
    c = make_client(fake_users, forum=fake_forum, notifications=fake_notifications)
    pid = _post_as(c, "bob")
    _vote_as(c, "alice", pid, 1)                     # first ping
    for n in fake_notifications._items:              # simulate the coalesce window elapsing
        if n["type"] == "vote":
            n["created_at"] -= 3600
    _vote_as(c, "alice", pid, -1)                    # a genuinely later vote -> a fresh, separate ping
    _login(c, "bob")
    assert len(_vote_notes(c, unread_only=True)) == 2  # two real engagements, two pings (not muted)


def test_vote_succeeds_even_if_the_notification_store_is_down(make_client, fake_users, fake_forum):
    """Best-effort: the author-ping must never turn a valid vote into an error."""
    class BrokenNotifications:
        def add(self, *a, **k):
            raise RuntimeError("notification store down")

        def list(self, *a, **k):
            raise RuntimeError("notification store down")

        def mark_read(self, *a, **k):
            raise RuntimeError("notification store down")

    c = make_client(fake_users, forum=fake_forum, notifications=BrokenNotifications())
    _login(c, "bob")
    pid = c.post("/forum/posts", json={"title": "T", "body": "b"}).get_json()["post"]["id"]
    c.post("/logout")
    _login(c, "alice")
    assert _vote(c, pid, 1).get_json()["score"] == 1  # vote still lands despite the dead notification store
