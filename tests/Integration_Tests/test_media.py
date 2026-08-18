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
