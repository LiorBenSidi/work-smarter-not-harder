"""Integration tests — Forum/DM media attachments (OWNER: Elad).

Exercises the new media blueprint end-to-end through the Flask test client (in-process, injected fakes,
no Mongo/Docker): upload -> serve round-trip, and binding a blob to a post / to a DM then listing it via
the additive attachment endpoints (so forum.py / messages.py stay unmodified).
"""
import io

_PNG = b"\x89PNG\r\n\x1a\nfake-bytes"


def _login(c, user="mediauser"):
    c.post("/register", json={"username": user, "password": "s3cretpw!", "email": user + "@ex.com"})
    c.post("/login", json={"username": user, "password": "s3cretpw!"})


def _upload_png(c, data=_PNG):
    return c.post("/media", data={"file": (io.BytesIO(data), "pic.png", "image/png")})


def test_upload_then_serve_roundtrip(media_client):
    c = media_client
    _login(c)
    r = _upload_png(c)
    assert r.status_code == 201
    body = r.get_json()
    mid = body["id"]
    assert body["url"] == f"/media/{mid}"
    got = c.get(f"/media/{mid}")
    assert got.status_code == 200
    assert got.data == _PNG                      # the exact bytes come back


def test_served_media_carries_a_download_name_with_extension(media_client):
    # #338 item 6: saving an attachment must yield a real filename WITH its extension, not a bare uuid the
    # OS can't open. serve() sets a Content-Disposition download_name carrying the mime's extension.
    c = media_client
    _login(c)
    mid = _upload_png(c).get_json()["id"]
    disp = c.get(f"/media/{mid}").headers.get("Content-Disposition", "")
    assert ".png" in disp                          # the extension is present in the download name
    assert mid in disp                             # ...and it's the stable, unique id (traceable)


def test_missing_file_on_disk_serves_a_clean_404(media_client):
    # #338 item 7 (backend): if the blob is gone from the volume but the record remains, serve() must return
    # a clean JSON 404 — not leak a Werkzeug HTML error page / 500 that the SPA can't reason about.
    import os
    c = media_client
    _login(c)
    mid = _upload_png(c).get_json()["id"]
    root = c.raw.application.config["MEDIA_ROOT"]
    os.remove(os.path.join(root, mid + ".png"))    # simulate a lost/rotated volume file
    r = c.get(f"/media/{mid}")
    assert r.status_code == 404
    assert r.is_json and "error" in r.get_json()   # structured, not an HTML crash page


def test_attach_to_post_then_list(media_client):
    c = media_client
    _login(c)
    mid = _upload_png(c).get_json()["id"]
    pid = c.post("/forum/posts", json={"title": "with media", "body": "see attachment"}).get_json()["post"]["id"]
    assert c.post(f"/forum/posts/{pid}/attachments", json={"attachment_ids": [mid]}).get_json()["bound"] == [mid]
    listing = c.get(f"/forum/posts/{pid}/attachments").get_json()["attachments"]
    assert [a["id"] for a in listing] == [mid]
    assert listing[0]["url"] == f"/media/{mid}"


def test_attach_to_dm_then_list(media_client):
    c = media_client
    _login(c, "alice")
    mid = _upload_png(c).get_json()["id"]
    assert c.post("/messages/bob/attachments", json={"attachment_ids": [mid]}).get_json()["bound"] == [mid]
    listing = c.get("/messages/bob/attachments").get_json()["attachments"]
    assert [a["id"] for a in listing] == [mid]


def test_dm_attachment_carries_owner_and_created_at_for_inline_placement(media_client):
    # The DM view weaves each image into the message timeline in the SENDER's column at the moment it was
    # shared, so the listing must expose the uploader (owner) and a created_at to sort/position by.
    c = media_client
    _login(c, "alice")
    mid = _upload_png(c).get_json()["id"]
    c.post("/messages/bob/attachments", json={"attachment_ids": [mid]})
    att = c.get("/messages/bob/attachments").get_json()["attachments"][0]
    assert att["owner"] == "alice"                 # -> renders in alice's column
    assert isinstance(att["created_at"], (int, float)) and att["created_at"] > 0   # -> sorts into the timeline
    assert att["url"] == f"/media/{mid}" and att["mime"] == "image/png"


def test_upload_rejected_once_total_disk_cap_reached(media_client):
    # Issue #313: MEDIA_MAX_TOTAL_BYTES bounds the volume's TOTAL bytes, so a logged-in user can't fill
    # the VM's disk 10 MB at a time (a full disk wedges Mongo writes + logging). The check runs before
    # the write: once stored bytes are at/over the cap, the next upload 507s and nothing new is stored.
    import os
    c = media_client
    _login(c)
    app = c.raw.application
    app.config["MEDIA_MAX_TOTAL_BYTES"] = len(_PNG)   # 1st upload fills the cap exactly
    assert _upload_png(c).status_code == 201
    r = _upload_png(c)
    assert r.status_code == 507
    assert "storage" in r.get_json()["error"]
    stored = os.listdir(app.config["MEDIA_ROOT"])
    assert len(stored) == 1                            # the rejected upload left no bytes behind


def test_attachments_are_capped_per_target(media_client):
    # #331 (scale/availability): a single post/DM must not carry an unbounded attachment list — the serve
    # read (list_for_target) would then be unbounded too. The bind route caps how many blobs one target
    # can hold, so the list stays bounded no matter how many a user tries to bolt on.
    c = media_client
    _login(c)
    c.raw.application.config["MEDIA_MAX_ATTACHMENTS_PER_TARGET"] = 3
    pid = c.post("/forum/posts", json={"title": "many", "body": "b"}).get_json()["post"]["id"]
    ids = [_upload_png(c).get_json()["id"] for _ in range(5)]
    bound = c.post(f"/forum/posts/{pid}/attachments", json={"attachment_ids": ids}).get_json()["bound"]
    assert bound == ids[:3]                                    # only the first 3 attach; the rest are shed
    assert len(c.get(f"/forum/posts/{pid}/attachments").get_json()["attachments"]) == 3
    # a later, separate attach on the now-full target binds nothing (the cap is on the target, not the call)
    extra = _upload_png(c).get_json()["id"]
    assert c.post(f"/forum/posts/{pid}/attachments", json={"attachment_ids": [extra]}).get_json()["bound"] == []


# Cross-owner attach refusals (binding a foreign blob, attaching to a foreign or missing post) live in
# Negative_Tests/test_messages_media_negative.py, where the shared alice/bob fixtures express the same
# assertions in a third of the setup — and the foreign-blob case additionally proves the blob stays
# private afterwards.


# --------------------------------------------------------------- comment attachments (#407)
# TA Online-Forum sub-requirement #2: "Each comment should have a body, and the option to add images and
# videos to the comment as well." Posts and DMs supported media; comments did not. The store already
# accepted a "comment" target and `_can_view` already handled it — but nothing ever WROTE one, so the
# branch was dead code and the feature only LOOKED wired, while four documents claimed it worked.


def _post_and_comment(c, body="nice one"):
    """Create a post and a comment on it, returning both ids."""
    pid = c.post("/forum/posts", json={"title": "a post", "body": "body"}).get_json()["post"]["id"]
    cid = c.post(f"/forum/posts/{pid}/comments", json={"body": body}).get_json()["comment"]["id"]
    return pid, cid


def test_attach_to_comment_then_list(media_client):
    """The requirement itself: a comment can carry an image, and that image comes back on the comment."""
    c = media_client
    _login(c)
    mid = _upload_png(c).get_json()["id"]
    pid, cid = _post_and_comment(c)
    bound = c.post(f"/forum/posts/{pid}/comments/{cid}/attachments",
                   json={"attachment_ids": [mid]}).get_json()["bound"]
    assert bound == [mid]
    listing = c.get(f"/forum/posts/{pid}/comments/{cid}/attachments").get_json()["attachments"]
    assert [a["id"] for a in listing] == [mid]
    assert listing[0]["url"] == f"/media/{mid}"


def test_a_comment_attachment_is_served_to_any_logged_in_reader(media_client):
    """The forum is public to signed-in users, so a comment's image must render for readers who are not
    its author — otherwise attaching one is pointless. (A DM attachment stays restricted; that is
    asserted separately.)"""
    c = media_client
    _login(c, "author")
    mid = _upload_png(c).get_json()["id"]
    pid, cid = _post_and_comment(c)
    c.post(f"/forum/posts/{pid}/comments/{cid}/attachments", json={"attachment_ids": [mid]})
    c.post("/logout")
    _login(c, "reader")
    assert c.get(f"/media/{mid}").status_code == 200
    assert [a["id"] for a in
            c.get(f"/forum/posts/{pid}/comments/{cid}/attachments").get_json()["attachments"]] == [mid]


def test_only_the_comments_author_can_attach_to_it(media_client):
    """Without the gate, any logged-in user could bolt their blob onto anyone's comment."""
    c = media_client
    _login(c, "author")
    pid, cid = _post_and_comment(c)
    c.post("/logout")
    _login(c, "intruder")
    mid = _upload_png(c).get_json()["id"]
    r = c.post(f"/forum/posts/{pid}/comments/{cid}/attachments", json={"attachment_ids": [mid]})
    assert r.status_code == 403
    assert c.get(f"/forum/posts/{pid}/comments/{cid}/attachments").get_json()["attachments"] == []


def test_attaching_to_a_missing_comment_is_404(media_client):
    c = media_client
    _login(c)
    mid = _upload_png(c).get_json()["id"]
    pid, _ = _post_and_comment(c)
    r = c.post(f"/forum/posts/{pid}/comments/nope/attachments", json={"attachment_ids": [mid]})
    assert r.status_code == 404


def test_a_comments_attachments_are_scoped_to_that_comment(media_client):
    """Two comments on the same post must not share a bucket — the target id carries both ids."""
    c = media_client
    _login(c)
    pid, first = _post_and_comment(c, "first")
    second = c.post(f"/forum/posts/{pid}/comments", json={"body": "second"}).get_json()["comment"]["id"]
    mid = _upload_png(c).get_json()["id"]
    c.post(f"/forum/posts/{pid}/comments/{first}/attachments", json={"attachment_ids": [mid]})
    assert [a["id"] for a in
            c.get(f"/forum/posts/{pid}/comments/{first}/attachments").get_json()["attachments"]] == [mid]
    assert c.get(f"/forum/posts/{pid}/comments/{second}/attachments").get_json()["attachments"] == []


def test_a_comment_attachment_does_not_leak_onto_its_post(media_client):
    """The post and its comments are different targets; a comment's image must not appear on the post."""
    c = media_client
    _login(c)
    pid, cid = _post_and_comment(c)
    mid = _upload_png(c).get_json()["id"]
    c.post(f"/forum/posts/{pid}/comments/{cid}/attachments", json={"attachment_ids": [mid]})
    assert c.get(f"/forum/posts/{pid}/attachments").get_json()["attachments"] == []


def test_comment_attachments_require_auth(media_client):
    c = media_client
    _login(c)
    pid, cid = _post_and_comment(c)
    c.post("/logout")
    assert c.get(f"/forum/posts/{pid}/comments/{cid}/attachments").status_code == 401
    assert c.post(f"/forum/posts/{pid}/comments/{cid}/attachments",
                  json={"attachment_ids": []}).status_code == 401
