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


def test_many_comments_attachments_come_back_in_one_request(media_client):
    """#407 follow-up: asking per comment was an N+1 at the BROWSER layer. A page holds up to 50
    comments, and 50 parallel requests against a ~6-connection-per-origin limit made every other
    request — the forum feed included — queue behind the burst. Measured on the running app before the
    fix: opening a post with 20 comments issued 20 requests; after, one."""
    c = media_client
    _login(c)
    pid = c.post("/forum/posts", json={"title": "batch", "body": "b"}).get_json()["post"]["id"]
    cids, mids = [], []
    for i in range(3):
        cid = c.post(f"/forum/posts/{pid}/comments", json={"body": f"c{i}"}).get_json()["comment"]["id"]
        mid = _upload_png(c).get_json()["id"]
        c.post(f"/forum/posts/{pid}/comments/{cid}/attachments", json={"attachment_ids": [mid]})
        cids.append(cid)
        mids.append(mid)

    r = c.post(f"/forum/posts/{pid}/comments/attachments", json={"comment_ids": cids})
    assert r.status_code == 200
    grouped = r.get_json()["attachments"]
    assert set(grouped) == set(cids)                                  # every comment keyed by ITS id
    for cid, mid in zip(cids, mids):
        assert [a["id"] for a in grouped[cid]] == [mid]
        assert grouped[cid][0]["url"] == f"/media/{mid}"


def test_the_batch_read_omits_comments_with_no_media(media_client):
    """A comment with nothing attached must not come back as an empty key — the client treats presence
    as 'this comment has media', and an empty list would render an empty attachment strip."""
    c = media_client
    _login(c)
    pid, cid = _post_and_comment(c)
    bare = c.post(f"/forum/posts/{pid}/comments", json={"body": "no media"}).get_json()["comment"]["id"]
    mid = _upload_png(c).get_json()["id"]
    c.post(f"/forum/posts/{pid}/comments/{cid}/attachments", json={"attachment_ids": [mid]})

    grouped = c.post(f"/forum/posts/{pid}/comments/attachments",
                     json={"comment_ids": [cid, bare]}).get_json()["attachments"]
    assert list(grouped) == [cid]


def test_the_batch_read_is_scoped_to_the_post_in_the_url(media_client):
    """The target id carries both ids, so asking post A for post B's comment must return nothing —
    otherwise the batch route would be a way to read attachments across posts."""
    c = media_client
    _login(c)
    pid_a, cid_a = _post_and_comment(c)
    pid_b = c.post("/forum/posts", json={"title": "other", "body": "b"}).get_json()["post"]["id"]
    mid = _upload_png(c).get_json()["id"]
    c.post(f"/forum/posts/{pid_a}/comments/{cid_a}/attachments", json={"attachment_ids": [mid]})

    grouped = c.post(f"/forum/posts/{pid_b}/comments/attachments",
                     json={"comment_ids": [cid_a]}).get_json()["attachments"]
    assert grouped == {}


def test_the_batch_read_rejects_a_non_list_of_strings(media_client):
    """Same NoSQL-injection gate as the attach routes: these ids reach a query."""
    c = media_client
    _login(c)
    pid, _ = _post_and_comment(c)
    assert c.post(f"/forum/posts/{pid}/comments/attachments",
                  json={"comment_ids": {"$ne": ""}}).status_code == 400
    assert c.post(f"/forum/posts/{pid}/comments/attachments",
                  json={"comment_ids": [1, 2]}).status_code == 400


def test_the_batch_read_requires_auth(media_client):
    c = media_client
    _login(c)
    pid, cid = _post_and_comment(c)
    c.post("/logout")
    assert c.post(f"/forum/posts/{pid}/comments/attachments",
                  json={"comment_ids": [cid]}).status_code == 401

# ------------------------------------------------- media-only DMs notify the recipient (#408)
# TA Online-Forum sub-requirement #5: "The clients will get a notification on the webapp when they
# receive a new direct message." A DM sent as media with NO text produced nothing for the recipient —
# no notification, no unread badge, no inbox row, no live push — because attachments bind to the
# CONVERSATION, not to a message, so a media-only send had no message to hang any of that on. It
# surfaced only if they already had that exact thread open, via the 15s poll backstop.


def _media_only_send(c, to, ids):
    return c.post("/messages", json={"to": to, "body": "", "attachment_ids": ids})


def test_a_media_only_dm_notifies_the_recipient(media_client):
    """The requirement itself: sending a photo with no caption must reach the recipient like any DM."""
    c = media_client
    _login(c, "alice")
    mid = _upload_png(c).get_json()["id"]
    c.post("/register", json={"username": "bob", "password": "s3cretpw!", "email": "bob@ex.com"})
    assert _media_only_send(c, "bob", [mid]).status_code == 201
    c.post("/messages/bob/attachments", json={"attachment_ids": [mid]})

    c.post("/login", json={"username": "bob", "password": "s3cretpw!"})
    data = c.get("/notifications").get_json()
    assert data["unread"] == 1
    assert data["notifications"][0]["type"] == "dm"
    assert data["notifications"][0]["actor"] == "alice"


def test_a_media_only_dm_creates_an_inbox_row_with_an_unread_count(media_client):
    """The inbox is derived from the messages collection, so with no message there was no row at all —
    the conversation simply did not exist for the recipient until they opened that exact thread."""
    c = media_client
    _login(c, "alice")
    mid = _upload_png(c).get_json()["id"]
    c.post("/register", json={"username": "bob", "password": "s3cretpw!", "email": "bob@ex.com"})
    _media_only_send(c, "bob", [mid])

    c.post("/login", json={"username": "bob", "password": "s3cretpw!"})
    convos = c.get("/conversations").get_json()["conversations"]
    assert [x["peer"] for x in convos] == ["alice"]
    assert convos[0]["unread"] == 1


def test_a_media_only_dm_stores_an_empty_body(media_client):
    """The message exists to carry the notification, not text. Keeping the body EMPTY (rather than
    inventing a caption like "Photo") matters: a fabricated body would land in the recipient's thread
    and in the GDPR export as words the sender never wrote. The client renders the image instead."""
    c = media_client
    _login(c, "alice")
    mid = _upload_png(c).get_json()["id"]
    c.post("/register", json={"username": "bob", "password": "s3cretpw!", "email": "bob@ex.com"})
    _media_only_send(c, "bob", [mid])

    c.post("/login", json={"username": "bob", "password": "s3cretpw!"})
    thread = c.get("/conversations/alice").get_json()["messages"]
    assert [m["body"] for m in thread] == [""]


def test_an_empty_dm_naming_someone_elses_blob_is_refused(media_client):
    """The anti-spam gate. Without it, `{"body": "", "attachment_ids": ["anything"]}` is a way to send
    someone an endless stream of blank messages, each one a notification and an unread badge."""
    c = media_client
    _login(c, "alice")
    mid = _upload_png(c).get_json()["id"]          # alice's blob
    c.post("/logout")
    c.post("/register", json={"username": "mallory", "password": "s3cretpw!", "email": "m@ex.com"})
    c.post("/login", json={"username": "mallory", "password": "s3cretpw!"})
    r = _media_only_send(c, "alice", [mid])        # mallory names a blob she does not own
    assert r.status_code == 400
    assert c.get("/conversations").get_json()["conversations"] == []


def test_an_empty_dm_naming_a_nonexistent_blob_is_refused(media_client):
    c = media_client
    _login(c, "alice")
    c.post("/register", json={"username": "bob", "password": "s3cretpw!", "email": "bob@ex.com"})
    assert _media_only_send(c, "bob", ["no-such-blob"]).status_code == 400


def test_an_empty_dm_with_no_attachments_is_still_refused(media_client):
    """The original validation is unchanged: an empty message with nothing attached is not a message."""
    c = media_client
    _login(c, "alice")
    c.post("/register", json={"username": "bob", "password": "s3cretpw!", "email": "bob@ex.com"})
    assert c.post("/messages", json={"to": "bob", "body": ""}).status_code == 400
    assert c.post("/messages", json={"to": "bob", "body": "   ", "attachment_ids": []}).status_code == 400


def test_a_text_dm_carrying_attachment_ids_still_sends(media_client):
    """Text + media is the common case and must be untouched by the empty-body path."""
    c = media_client
    _login(c, "alice")
    mid = _upload_png(c).get_json()["id"]
    c.post("/register", json={"username": "bob", "password": "s3cretpw!", "email": "bob@ex.com"})
    r = c.post("/messages", json={"to": "bob", "body": "look at this", "attachment_ids": [mid]})
    assert r.status_code == 201
    c.post("/login", json={"username": "bob", "password": "s3cretpw!"})
    assert [m["body"] for m in c.get("/conversations/alice").get_json()["messages"]] == ["look at this"]


def test_attachment_ids_must_be_a_list_of_strings(media_client):
    """The same NoSQL-injection gate the rest of the payload gets."""
    c = media_client
    _login(c, "alice")
    c.post("/register", json={"username": "bob", "password": "s3cretpw!", "email": "bob@ex.com"})
    assert c.post("/messages", json={"to": "bob", "body": "hi", "attachment_ids": {"$ne": ""}}).status_code == 400
    assert c.post("/messages", json={"to": "bob", "body": "hi", "attachment_ids": [1, 2]}).status_code == 400


def test_the_notification_names_an_attachment_when_the_dm_carries_no_text(media_client):
    """A media-only DM says "sent you an attachment"; a text DM says "sent you a message".

    The recipient acts on the notification text alone — the badge is all they see until they open the
    thread. Calling a photo "a message" sends them looking for words that were never written. #434
    mutation: hard-coding the text to "sent you a message" left the whole suite green, so the branch
    that picks the wording had no test at all.
    """
    c = media_client
    _login(c, "alice")
    mid = _upload_png(c).get_json()["id"]
    c.post("/register", json={"username": "bob", "password": "s3cretpw!", "email": "bob@ex.com"})
    assert _media_only_send(c, "bob", [mid]).status_code == 201
    assert c.post("/messages", json={"to": "bob", "body": "and here's why"}).status_code == 201

    c.post("/login", json={"username": "bob", "password": "s3cretpw!"})
    texts = [n["text"] for n in c.get("/notifications").get_json()["notifications"]]
    assert sorted(texts) == ["sent you a message", "sent you an attachment"]
