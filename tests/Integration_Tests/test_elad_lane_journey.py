"""Cross-feature journey over Elad's lane ONLY — media × engagement × upload caps × privacy.

Each of these features has its own suite (`test_media.py`, `test_engagement.py`,
`test_media_limits.py`); this file proves they compose. That is a different failure surface: the
per-feature tests all stay green if, say, binding media to a post breaks the vote bookkeeping the
engagement metric reads, or the per-request upload cap starts leaking onto the JSON routes the
journey uses in between. In-process (Flask test client + injected fakes) so it runs in every CI
without a stack; the same flow over real HTTP lives in `System_Tests/test_elad_lane_live.py`.

Deliberately does NOT touch teammates' features beyond their public contracts (register/login,
post/comment/vote are the recorded seams the media + engagement lanes were built against).
"""
import io

_PNG = b"\x89PNG\r\n\x1a\nfake-bytes"


def _login(c, user):
    c.post("/register", json={"username": user, "password": "s3cretpw!", "email": user + "@ex.com"})
    c.post("/login", json={"username": user, "password": "s3cretpw!"})


def _switch(c, user):
    c.post("/logout")
    _login(c, user)


def _upload_png(c, data=_PNG):
    return c.post("/media", data={"file": (io.BytesIO(data), "pic.png", "image/png")})


def test_media_votes_and_engagement_compose_across_two_users(media_client):
    """The whole lane in one sitting: author posts with media, a reader consumes the media and
    votes, and the author's personal metric reflects exactly that engagement."""
    c = media_client

    # -- Alice: post + comment, upload, bind ------------------------------------------------
    _login(c, "alice")
    pid = c.post("/forum/posts", json={"title": "route tips", "body": "hills"}).get_json()["post"]["id"]
    cid = c.post(f"/forum/posts/{pid}/comments", json={"body": "adding my map"}).get_json()["comment"]["id"]
    mid = _upload_png(c).get_json()["id"]
    assert c.post(f"/forum/posts/{pid}/attachments",
                  json={"attachment_ids": [mid]}).get_json()["bound"] == [mid]
    # her own metric starts clean — uploading/binding media is not engagement
    assert c.get("/me/engagement").get_json() == {"up": 0, "down": 0, "score": 0}

    # -- Bob: reads the attachment, then engages --------------------------------------------
    _switch(c, "bob")
    listed = c.get(f"/forum/posts/{pid}/attachments").get_json()["attachments"]
    assert [a["id"] for a in listed] == [mid]
    served = c.get(f"/media/{mid}")
    assert served.status_code == 200 and served.data == _PNG   # bound media is public to a reader
    assert c.post(f"/forum/posts/{pid}/vote", json={"value": 1}).status_code == 200
    assert c.post(f"/forum/posts/{pid}/comments/{cid}/vote", json={"value": 1}).status_code == 200
    # engagement is per-author: Bob GAVE votes, he received none
    assert c.get("/me/engagement").get_json() == {"up": 0, "down": 0, "score": 0}

    # -- Alice: the metric shows exactly Bob's two votes ------------------------------------
    _switch(c, "alice")
    assert c.get("/me/engagement").get_json() == {"up": 2, "down": 0, "score": 2}


def test_upload_caps_hold_mid_journey_without_breaking_the_json_routes(media_client):
    """The per-request upload cap (413) and MIME allowlist (400) engage during a working session —
    and the raised cap stays scoped to POST /media, so the small-JSON guard on the routes the
    journey keeps using is untouched."""
    c = media_client
    c.raw.application.config["MEDIA_MAX_BYTES"] = 1024

    _login(c, "carol")
    pid = c.post("/forum/posts", json={"title": "t", "body": "b"}).get_json()["post"]["id"]

    assert _upload_png(c, b"x" * 2048).status_code == 413            # over the cap -> rejected unread
    bad_type = c.post("/media", data={"file": (io.BytesIO(b"#!/bin/sh"), "x.sh", "text/x-sh")})
    assert bad_type.status_code == 400                               # MIME allowlist

    mid = _upload_png(c, b"ok" * 100).get_json()["id"]               # a legal upload still works
    assert c.post(f"/forum/posts/{pid}/attachments",
                  json={"attachment_ids": [mid]}).get_json()["bound"] == [mid]
    # the JSON routes' 64 KB guard survived the raised-then-restored upload cap
    assert c.post("/forum/posts", json={"title": "t2", "body": "b" * 70_000}).status_code == 413


def test_anonymous_post_media_is_public_but_engagement_still_reaches_the_author(media_client):
    """Anonymity is a display projection: a reader sees the attachment but not the author, while
    the author's own personal area still counts the votes that post earns."""
    c = media_client
    _login(c, "dana")
    pid = c.post("/forum/posts",
                 json={"title": "anon", "body": "b", "anonymous": True}).get_json()["post"]["id"]
    mid = _upload_png(c).get_json()["id"]
    c.post(f"/forum/posts/{pid}/attachments", json={"attachment_ids": [mid]})

    _switch(c, "eve")
    post = c.get(f"/forum/posts/{pid}").get_json()["post"]
    assert post["author"] == "Anonymous"                             # reader never sees dana
    assert c.get(f"/media/{mid}").status_code == 200                 # but the media is readable
    c.post(f"/forum/posts/{pid}/vote", json={"value": -1})

    _switch(c, "dana")
    assert c.get("/me/engagement").get_json() == {"up": 0, "down": 1, "score": -1}


def test_the_lane_is_fully_auth_gated_when_the_session_ends(media_client):
    """Logout mid-journey: every endpoint the journey used goes dark at once."""
    c = media_client
    _login(c, "frank")
    pid = c.post("/forum/posts", json={"title": "t", "body": "b"}).get_json()["post"]["id"]
    mid = _upload_png(c).get_json()["id"]
    c.post(f"/forum/posts/{pid}/attachments", json={"attachment_ids": [mid]})
    c.post("/logout")

    assert c.get("/me/engagement").status_code == 401
    assert c.get(f"/media/{mid}").status_code == 401
    assert c.post("/media", data={"file": (io.BytesIO(_PNG), "p.png", "image/png")}).status_code == 401
    assert c.post(f"/forum/posts/{pid}/attachments", json={"attachment_ids": [mid]}).status_code == 401
