"""Integration tests for the Forum CRUD (posts / comments / votes). OWNER: Lior."""
import pytest


def _login(c, username="alice"):
    c.post("/register", json={"username": username, "password": "s3cretpw!", "email": f"{username}@example.com"})
    c.post("/login", json={"username": username, "password": "s3cretpw!"})


def _new_post(c, title="First", body="hello"):
    return c.post("/forum/posts", json={"title": title, "body": body})


def test_create_then_list_posts(forum_client):
    """A post created over HTTP appears in the feed carrying its title, its author and a starting score — the round trip a user actually performs."""
    _login(forum_client)
    assert _new_post(forum_client).status_code == 201
    posts = forum_client.get("/forum/posts").get_json()["posts"]
    assert len(posts) == 1
    assert posts[0]["title"] == "First"
    assert posts[0]["author"] == "alice"
    assert posts[0]["score"] == 0


def test_list_posts_carry_created_at_in_creation_order(forum_client):
    """The client sorts the feed by creation time and renders each post's age, so every summary row must carry a positive timestamp and a later post must be strictly newer than an earlier one."""
    _login(forum_client)
    _new_post(forum_client, "one", "a")
    _new_post(forum_client, "two", "b")
    posts = {p["title"]: p for p in forum_client.get("/forum/posts").get_json()["posts"]}
    assert posts["one"]["created_at"] > 0 and posts["two"]["created_at"] > 0
    assert posts["two"]["created_at"] > posts["one"]["created_at"]   # the later post is strictly newer


def test_forum_feed_pages_back_to_the_oldest_via_next_before(forum_client):
    """Walking the feed's cursor reaches EVERY post, newest-first, exactly once — so a reader can get to the oldest post without any single request being unbounded."""
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
    """A page that is not full means nothing older remains, so the cursor comes back empty and the client knows to stop rather than looping forever."""
    _login(forum_client)
    _new_post(forum_client, "only", "b")
    data = forum_client.get("/forum/posts?limit=5").get_json()
    assert len(data["posts"]) == 1
    assert data["next_before"] is None


@pytest.mark.parametrize("cursor", ["not-a-number", "nan", "inf", "-inf"])
def test_forum_feed_ignores_a_garbage_before_cursor(forum_client, cursor):
    """A garbage cursor falls back to the newest page — never a 500, and never an unbounded scan someone could trigger by hand.

    The two kinds of garbage take DIFFERENT paths, and only one of them reaches the route's guard.
    `not-a-number` never gets there: Flask's `type=float` swallows the parse error and hands the route
    `None`. `nan` / `inf` DO parse — `float("nan")` is a perfectly valid float — so they are the only
    inputs that exercise the `math.isfinite` check, and a nan cursor reaching the store is exactly what
    would turn a paged read into a scan. Measured before adding them: deleting that guard entirely left
    the whole suite green (1084 passed), because `not-a-number` was the only case anyone ever sent.
    """
    _login(forum_client)
    _new_post(forum_client, "hi", "b")
    resp = forum_client.get("/forum/posts?before=" + cursor)
    assert resp.status_code == 200
    assert [p["title"] for p in resp.get_json()["posts"]] == ["hi"]


def test_forum_feed_reports_each_posts_comment_count(forum_client):
    """Every row in the feed carries how many comments its post has, which is what the list shows under each title.

    Nothing asserted it: hard-coding the feed's `comments` field to 0 left the whole suite green
    (measured, 1084 passed). The detail view's comment LIST is well covered, but the feed's COUNT is a
    different field with its own fallback, and no test read it.
    """
    _login(forum_client)
    pid = _new_post(forum_client, "counted", "b").get_json()["post"]["id"]
    for body in ("one", "two", "three"):
        forum_client.post("/forum/posts/" + pid + "/comments", json={"body": body})
    row = next(p for p in forum_client.get("/forum/posts").get_json()["posts"] if p["id"] == pid)
    assert row["comments"] == 3, f"the feed must report the post's comment count, got {row['comments']}"


def test_get_post_with_its_comments(forum_client):
    """The post detail carries a comment COUNT rather than the comments themselves, which are fetched from their own paginated endpoint — so opening a post with thousands of replies stays one small response."""
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
    """Walking a post's comment cursor reaches every comment, newest-first, exactly once, so even the oldest reply is reachable without an unbounded read."""
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
    """A malformed comment cursor falls back to the newest page rather than erroring, so a stale or hand-edited link still renders something."""
    _login(forum_client)
    pid = _new_post(forum_client, "T", "b").get_json()["post"]["id"]
    forum_client.post(f"/forum/posts/{pid}/comments", json={"body": "hi"})
    resp = forum_client.get(f"/forum/posts/{pid}/comments?before=not-a-number")
    assert resp.status_code == 200
    assert [c["body"] for c in resp.get_json()["comments"]] == ["hi"]


def test_comments_endpoint_requires_login(forum_client):
    """Reading a thread's comments is gated, so the forum is not readable by anyone who happens to know a post id."""
    assert forum_client.get("/forum/posts/whatever/comments").status_code == 401


def test_vote_changes_score_and_one_vote_per_user(forum_client):
    """A vote moves the score, and voting again REPLACES the previous vote rather than adding to it — so one person cannot drive a post's score by clicking repeatedly."""
    _login(forum_client)
    pid = _new_post(forum_client, "T", "b").get_json()["post"]["id"]
    assert forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 1}).get_json()["score"] == 1
    # re-voting replaces the previous vote (not additive)
    assert forum_client.post(f"/forum/posts/{pid}/vote", json={"value": -1}).get_json()["score"] == -1


def test_anonymous_post_hides_the_author(forum_client):
    """A post submitted anonymously shows no author in the feed, which is the entire promise made to whoever chose that option."""
    _login(forum_client)
    forum_client.post("/forum/posts", json={"title": "T", "body": "b", "anonymous": True})
    assert forum_client.get("/forum/posts").get_json()["posts"][0]["author"] == "Anonymous"


def test_comment_on_missing_post_is_404(forum_client):
    """Commenting on a post that does not exist is a 404, so no orphan comment is created against a phantom thread."""
    _login(forum_client)
    assert forum_client.post("/forum/posts/999/comments", json={"body": "x"}).status_code == 404


def test_get_missing_post_is_404(forum_client):
    """Requesting a post that does not exist is a 404 rather than an empty success that would render as a blank page."""
    _login(forum_client)
    assert forum_client.get("/forum/posts/999").status_code == 404


def test_author_can_edit_their_post(forum_client):
    """An author can edit their own post, and the edit is what subsequent readers get — not a stale copy served from somewhere else."""
    _login(forum_client)
    pid = _new_post(forum_client, "Old", "old body").get_json()["post"]["id"]
    resp = forum_client.patch(f"/forum/posts/{pid}", json={"title": "New", "body": "new body"})
    assert resp.status_code == 200
    assert resp.get_json()["post"]["title"] == "New"
    assert forum_client.get(f"/forum/posts/{pid}").get_json()["post"]["body"] == "new body"


def test_author_can_delete_their_post(forum_client):
    """An author can delete their own post, and it disappears from both the direct link and the feed rather than lingering in one of them."""
    _login(forum_client)
    pid = _new_post(forum_client).get_json()["post"]["id"]
    assert forum_client.delete(f"/forum/posts/{pid}").status_code == 200
    assert forum_client.get(f"/forum/posts/{pid}").status_code == 404  # gone
    assert forum_client.get("/forum/posts").get_json()["posts"] == []


def test_edit_missing_post_is_404(forum_client):
    """Editing a post that does not exist is a 404, distinguishing "gone" from "not yours" so the client can say the right thing."""
    _login(forum_client)
    assert forum_client.patch("/forum/posts/999", json={"title": "X", "body": "y"}).status_code == 404


# (The empty-title PATCH wall is proven in Negative_Tests with the same input, alongside the
#  over-length wall and a "the refusal changed nothing" assertion. test_edit_missing_post_is_404
#  above stays: PATCH is absent from that file's unknown-post sweep.)


def test_votes_aggregate_across_users(forum_client):
    """One vote per person, but DIFFERENT people's votes sum into the score — the alternative, last-write-wins, would make the score meaningless."""
    _login(forum_client, "alice")
    pid = _new_post(forum_client).get_json()["post"]["id"]
    assert forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 1}).get_json()["score"] == 1
    forum_client.post("/logout")
    _login(forum_client, "bob")
    assert forum_client.post(f"/forum/posts/{pid}/vote", json={"value": 1}).get_json()["score"] == 2


def test_feed_and_detail_publish_like_and_dislike_tallies(forum_client):
    """A client must be able to see how many likes a post has, and the net score cannot show that: a contested post and an untouched one both sit at zero.

    Both the feed row and the detail carry the two tallies, while the voter identities never leave the server.
    """
    _login(forum_client, "alice")
    hot = _new_post(forum_client, "Contested", "b").get_json()["post"]["id"]
    _new_post(forum_client, "Quiet", "b")
    forum_client.post(f"/forum/posts/{hot}/vote", json={"value": 1})
    forum_client.post("/logout")
    _login(forum_client, "bob")
    forum_client.post(f"/forum/posts/{hot}/vote", json={"value": -1})

    feed = {p["title"]: p for p in forum_client.get("/forum/posts").get_json()["posts"]}
    assert feed["Contested"]["score"] == feed["Quiet"]["score"] == 0        # the net cannot tell them apart
    assert (feed["Contested"]["likes"], feed["Contested"]["dislikes"]) == (1, 1)
    assert (feed["Quiet"]["likes"], feed["Quiet"]["dislikes"]) == (0, 0)

    detail = forum_client.get(f"/forum/posts/{hot}").get_json()["post"]
    assert (detail["likes"], detail["dislikes"]) == (1, 1)
    assert "votes" not in detail                                           # counts ship; voters never do
