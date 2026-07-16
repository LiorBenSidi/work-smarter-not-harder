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
    r = poster.post("/forum/posts", json=payload)
    assert r.status_code == 400, f"{payload!r} must be refused, got {r.status_code}"
    assert poster.get("/forum/posts").get_json()["posts"] == [], "a refused post must never be stored"


def test_edit_rejects_the_same_walls_as_create(poster):
    pid = _pid(poster)
    assert poster.patch(f"/forum/posts/{pid}", json={"title": "", "body": "b"}).status_code == 400
    assert poster.patch(f"/forum/posts/{pid}", json={"title": "t", "body": "x" * 5001}).status_code == 400
    # the refusals changed nothing.
    post = poster.get(f"/forum/posts/{pid}").get_json()["post"]
    assert post["title"] == "target" and post["body"] == "body"


# --------------------------------------------------------------- unknown targets

def test_unknown_post_is_404_everywhere(poster):
    assert poster.get("/forum/posts/nope").status_code == 404
    assert poster.post("/forum/posts/nope/comments", json={"body": "hi"}).status_code == 404
    assert poster.post("/forum/posts/nope/vote", json={"value": 1}).status_code == 404
    assert poster.delete("/forum/posts/nope").status_code == 404


def test_unknown_comment_vote_is_404_even_on_a_real_post(poster):
    pid = _pid(poster)
    assert poster.post(f"/forum/posts/{pid}/comments/c999/vote", json={"value": 1}).status_code == 404


# --------------------------------------------------------------- comment walls

@pytest.mark.parametrize("payload", [
    None, {}, {"body": ""}, {"body": "   "}, {"body": "x" * 2001}, {"body": 7}, {"body": {"$gt": ""}},
])
def test_comment_rejects_malformed_bodies(poster, payload):
    pid = _pid(poster)
    assert poster.post(f"/forum/posts/{pid}/comments", json=payload).status_code == 400
    assert poster.get(f"/forum/posts/{pid}").get_json()["post"]["comments"] == []


# --------------------------------------------------------------- vote walls (the bool trap included)

@pytest.mark.parametrize("value", [0, 2, -2, "1", 1.0, True, False, None, [1], {"$gt": 0}])
def test_vote_accepts_exactly_int_plus_minus_one(poster, value):
    # `type(value) is int` + membership: floats, bools (an int subclass!), strings all bounce.
    pid = _pid(poster)
    r = poster.post(f"/forum/posts/{pid}/vote", json={"value": value})
    assert r.status_code == 400, f"value={value!r} must be refused, got {r.status_code}"
    assert poster.get(f"/forum/posts/{pid}").get_json()["post"]["score"] == 0


def test_comment_vote_has_the_same_value_wall(poster):
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
    pid = _pid(poster)
    assert intruder.patch(f"/forum/posts/{pid}", json={"title": "hijacked", "body": "mine now"}
                          ).status_code == 403
    assert intruder.delete(f"/forum/posts/{pid}").status_code == 403
    post = poster.get(f"/forum/posts/{pid}").get_json()["post"]
    assert post["title"] == "target", "a refused edit must leave the post untouched"


def test_anonymity_survives_a_hostile_read(poster, intruder):
    pid = poster.post("/forum/posts", json={"title": "anon", "body": "b", "anonymous": True}
                      ).get_json()["post"]["id"]
    seen = intruder.get(f"/forum/posts/{pid}").get_json()["post"]
    assert seen["author"] == "Anonymous" and seen["mine"] is False
    listing = intruder.get("/forum/posts").get_json()["posts"]
    assert all(p["author"] == "Anonymous" for p in listing if p["id"] == pid)
