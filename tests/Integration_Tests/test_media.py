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


def test_cannot_attach_someone_elses_blob(media_client, make_client, fake_users, fake_forum,
                                          fake_messages, fake_media, fake_notifications, tmp_path):
    # alice uploads; bob (a second client sharing the same fake stores) can't bind alice's blob.
    _login(media_client, "alice")
    mid = _upload_png(media_client).get_json()["id"]
    bob = make_client(fake_users, forum=fake_forum, messages=fake_messages, media=fake_media,
                      notifications=fake_notifications)
    bob.raw.application.config["MEDIA_ROOT"] = str(tmp_path / "media")
    bob.post("/register", json={"username": "bob", "password": "s3cretpw!", "email": "bob@ex.com"})
    bob.post("/login", json={"username": "bob", "password": "s3cretpw!"})
    pid = bob.post("/forum/posts", json={"title": "hijack", "body": "not mine"}).get_json()["post"]["id"]
    assert bob.post(f"/forum/posts/{pid}/attachments", json={"attachment_ids": [mid]}).get_json()["bound"] == []


def test_cannot_attach_to_someone_elses_post(media_client, make_client, fake_users, fake_forum,
                                             fake_messages, fake_media, fake_notifications, tmp_path):
    # alice owns a post; bob (his OWN blob) can't bolt it onto her post -> 403 (post-ownership), and a
    # bogus post id -> 404. Without the check any logged-in user could attach media to anyone's post.
    _login(media_client, "alice")
    pid = media_client.post("/forum/posts", json={"title": "alice's", "body": "hers"}).get_json()["post"]["id"]
    bob = make_client(fake_users, forum=fake_forum, messages=fake_messages, media=fake_media,
                      notifications=fake_notifications)
    bob.raw.application.config["MEDIA_ROOT"] = str(tmp_path / "media")
    bob.post("/register", json={"username": "bob", "password": "s3cretpw!", "email": "bob@ex.com"})
    bob.post("/login", json={"username": "bob", "password": "s3cretpw!"})
    mid = _upload_png(bob).get_json()["id"]
    assert bob.post(f"/forum/posts/{pid}/attachments", json={"attachment_ids": [mid]}).status_code == 403
    assert bob.post("/forum/posts/nope/attachments", json={"attachment_ids": [mid]}).status_code == 404
