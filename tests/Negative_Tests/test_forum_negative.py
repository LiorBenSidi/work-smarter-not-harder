"""Negative tests — forum posts / comments / votes refuse bad input and foreign ownership. OWNER: Elad.

The forum's rejection contract: every malformed payload (length walls, wrong types, the bool-vote
trap), every unknown target (missing post / comment -> 404), and every ownership breach (edit /
delete someone else's post -> 403) — always a clean JSON 4xx, never a 5xx, never a silent write.
"""
import pytest


@pytest.fixture
def poster(forum_client):
    forum_client.post("/register", json={"username": "poster", "password": "s3cretpw!", "email": "p@ex.com"})
    forum_client.post("/login", json={"username": "poster", "password": "s3cretpw!"})
    return forum_client


def _pid(c, title="target"):
    return c.post("/forum/posts", json={"title": title, "body": "body"}).get_json()["post"]["id"]


# --------------------------------------------------------------- create/edit walls

@pytest.mark.parametrize("payload", [
    None, [], "post",
    {},                                                       # both fields missing
    {"title": "", "body": "b"},                               # empty title
    {"title": "   ", "body": "b"},                            # whitespace-only title
    {"title": "x" * 141, "body": "b"},                        # title over 140
    {"title": "t", "body": ""},                               # empty body
    {"title": "t", "body": "x" * 5001},                       # body over 5000
    {"title": "t", "body": "b", "anonymous": "yes"},          # anonymous must be a real bool
    {"title": ["t"], "body": "b"},                            # wrong types
    {"title": {"$gt": ""}, "body": "b"},                      # injection object
])
def test_create_post_rejects_malformed_payloads(poster, payload):
    """Every malformed post is refused with a 400 AND leaves the forum empty, so a rejection can never be a partial write.

    The second assertion is the one that earns this test's place: a route that validated after inserting
    would still answer 400 and pass a status-only check, while the bad row sat in the forum. The payloads
    are distinct input CLASSES, not values — missing fields, both length walls, the whitespace-only title,
    a non-bool `anonymous`, a wrong type, and a `$gt` injection object.
    """
    r = poster.post("/forum/posts", json=payload)
    assert r.status_code == 400, f"{payload!r} must be refused, got {r.status_code}"
    assert poster.get("/forum/posts").get_json()["posts"] == [], "a refused post must never be stored"


def test_edit_rejects_the_same_walls_as_create(poster):
    """Editing a post runs the SAME validator as creating one, and a refused edit leaves the post untouched.

    The two paths are separate handlers, so a wall added to create can silently miss edit — which would let
    anyone widen their own post past the length limits after the fact. Re-reading the post afterwards is
    what proves the refusal wrote nothing, rather than rejecting after a partial update.
    """
    pid = _pid(poster)
    assert poster.patch(f"/forum/posts/{pid}", json={"title": "", "body": "b"}).status_code == 400
    assert poster.patch(f"/forum/posts/{pid}", json={"title": "t", "body": "x" * 5001}).status_code == 400
    # the refusals changed nothing.
    post = poster.get(f"/forum/posts/{pid}").get_json()["post"]
    assert post["title"] == "target" and post["body"] == "body"


# --------------------------------------------------------------- unknown targets

def test_unknown_post_is_404_everywhere(poster):
    """All four verbs on a post that does not exist answer 404 — never a 500, and never a 403.

    Each verb looks the post up on its own path, so one of them can regress alone. A 500 would leak a stack
    trace; a 403 would confirm the id exists to someone probing for it.
    """
    assert poster.get("/forum/posts/nope").status_code == 404
    assert poster.post("/forum/posts/nope/comments", json={"body": "hi"}).status_code == 404
    assert poster.post("/forum/posts/nope/vote", json={"value": 1}).status_code == 404
    assert poster.delete("/forum/posts/nope").status_code == 404


def test_unknown_comment_vote_is_404_even_on_a_real_post(poster):
    """A vote on a missing COMMENT of a real post is 404, so the handler checks the comment id and not just the post id.

    The post exists here on purpose: a route that only resolved the post would find it, sail past, and try
    to tally a vote against nothing.
    """
    pid = _pid(poster)
    assert poster.post(f"/forum/posts/{pid}/comments/c999/vote", json={"value": 1}).status_code == 404


# --------------------------------------------------------------- comment walls

@pytest.mark.parametrize("payload", [
    None, {}, {"body": ""}, {"body": "   "}, {"body": "x" * 2001}, {"body": 7}, {"body": {"$gt": ""}},
])
def test_comment_rejects_malformed_bodies(poster, payload):
    """A refused comment leaves BOTH the post's comment count and the comment list untouched.

    The count is stored separately from the comments themselves (#331), so a validator that bumped the
    counter before rejecting the body would show a post claiming comments that cannot be read.
    """
    pid = _pid(poster)
    assert poster.post(f"/forum/posts/{pid}/comments", json=payload).status_code == 400
    assert poster.get(f"/forum/posts/{pid}").get_json()["post"]["comment_count"] == 0   # #331
    assert poster.get(f"/forum/posts/{pid}/comments").get_json()["comments"] == []


# --------------------------------------------------------------- vote walls (the bool trap included)

@pytest.mark.parametrize("value", [0, 2, -2, "1", 1.0, True, False, None, [1], {"$gt": 0}])
def test_vote_accepts_exactly_int_plus_minus_one(poster, value):
    """A vote value must be exactly the int 1 or -1, and every refusal leaves the score at 0.

    `True` and `False` are the trap this exists for: `bool` is an `int` subclass in Python, so a plain
    `value in (1, -1)` membership test accepts `True` as an upvote. The rest are distinct classes — out of
    range, a stringified number, a float that compares equal to 1, null, a list, and an injection object.
    """
    # `type(value) is int` + membership: floats, bools (an int subclass!), strings all bounce.
    pid = _pid(poster)
    r = poster.post(f"/forum/posts/{pid}/vote", json={"value": value})
    assert r.status_code == 400, f"value={value!r} must be refused, got {r.status_code}"
    assert poster.get(f"/forum/posts/{pid}").get_json()["post"]["score"] == 0


def test_comment_vote_has_the_same_value_wall(poster):
    """Comment votes enforce the same value wall as post votes, including the bool trap.

    It is a second handler with its own copy of the check, so the post-vote test above cannot cover it —
    the two have already been able to drift apart.
    """
    pid = _pid(poster)
    cid = poster.post(f"/forum/posts/{pid}/comments", json={"body": "c"}).get_json()["comment"]["id"]
    for value in (0, "1", True):
        assert poster.post(f"/forum/posts/{pid}/comments/{cid}/vote",
                           json={"value": value}).status_code == 400


# --------------------------------------------------------------- ownership breaches

@pytest.fixture
def intruder(make_client, fake_users, fake_forum, fake_notifications):
    c = make_client(fake_users, forum=fake_forum, notifications=fake_notifications)
    c.post("/register", json={"username": "intruder", "password": "s3cretpw!", "email": "i@ex.com"})
    c.post("/login", json={"username": "intruder", "password": "s3cretpw!"})
    return c


def test_editing_or_deleting_a_foreign_post_is_403_and_changes_nothing(poster, intruder):
    """A second, real, signed-in user cannot edit or delete somebody else's post, and the refusal changes nothing.

    Being authenticated is the point: this is the ownership check, not the login gate. Re-reading the title
    afterwards proves the 403 was returned instead of the write, not after it.
    """
    pid = _pid(poster)
    assert intruder.patch(f"/forum/posts/{pid}", json={"title": "hijacked", "body": "mine now"}
                          ).status_code == 403
    assert intruder.delete(f"/forum/posts/{pid}").status_code == 403
    post = poster.get(f"/forum/posts/{pid}").get_json()["post"]
    assert post["title"] == "target", "a refused edit must leave the post untouched"


def test_anonymity_survives_a_hostile_read(poster, intruder):
    """An anonymous post reads as "Anonymous" to somebody else through BOTH the detail route and the listing.

    The author name is redacted per response shape, so the two paths can disagree — and a listing that
    leaked the real name would undo the promise the checkbox makes at the moment of posting.
    """
    pid = poster.post("/forum/posts", json={"title": "anon", "body": "b", "anonymous": True}
                      ).get_json()["post"]["id"]
    seen = intruder.get(f"/forum/posts/{pid}").get_json()["post"]
    assert seen["author"] == "Anonymous" and seen["mine"] is False
    listing = intruder.get("/forum/posts").get_json()["posts"]
    assert all(p["author"] == "Anonymous" for p in listing if p["id"] == pid)
