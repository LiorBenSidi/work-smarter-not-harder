"""Security guard tests — media size / type / auth / DM-privacy (OWNER: Elad).

These lock the media contract so a later change (a teammate's or my own) that loosens the size cap,
the mime allowlist, the auth gate, or DM-attachment privacy fails CI. They run in normal CI (in-process
client + injected fakes, no live stack). The last test proves the per-request upload-size override does
NOT leak into the small 64 KB JSON body cap that guards the other routes.
"""
import io
import os

import pytest


def _login(c, user="mediauser"):
    c.post("/register", json={"username": user, "password": "s3cretpw!", "email": user + "@ex.com"})
    c.post("/login", json={"username": user, "password": "s3cretpw!"})


def test_oversize_upload_is_rejected_413_before_any_bytes_are_stored(media_client):
    # 413 alone is not the guarantee that matters: a cap that rejects *after* writing still lets a
    # flood fill the disk. Assert the store stayed empty too.
    c = media_client
    _login(c)
    app = c.raw.application
    app.config["MEDIA_MAX_BYTES"] = 1024                      # tiny per-file cap for the test
    r = c.post("/media", data={"file": (io.BytesIO(b"x" * 5000), "big.png", "image/png")})
    assert r.status_code == 413
    root = app.config["MEDIA_ROOT"]
    stored = os.listdir(root) if os.path.isdir(root) else []
    assert stored == [], "an oversize upload must die before any bytes are stored"


@pytest.mark.parametrize("mime", ["application/octet-stream", "text/plain", "application/x-msdownload",
                                  "image/svg+xml", "text/html", "application/json"])
def test_every_non_allowlisted_mime_is_rejected_400(media_client, mime):
    # allowlist, not blocklist: html/svg (script carriers) and executables all bounce the same way.
    c = media_client
    _login(c)
    r = c.post("/media", data={"file": (io.BytesIO(b"MZ\x90\x00"), "evil.bin", mime)})
    assert r.status_code == 400
    assert "unsupported" in r.get_json()["error"]


def test_unauthenticated_upload_is_401(media_client):
    r = media_client.post("/media", data={"file": (io.BytesIO(b"x"), "p.png", "image/png")})
    assert r.status_code == 401


def test_unauthenticated_serve_is_401(media_client):
    assert media_client.get("/media/anything").status_code == 401


def test_dm_media_is_private_to_participants(make_client, fake_users, fake_forum, fake_messages,
                                             fake_media, fake_notifications, tmp_path):
    # alice attaches a blob to a DM with bob; bob (a participant) may fetch it, carol (a third user) may not.
    def build():
        c = make_client(fake_users, forum=fake_forum, messages=fake_messages, media=fake_media,
                        notifications=fake_notifications)
        c.raw.application.config["MEDIA_ROOT"] = str(tmp_path / "media")
        return c

    clients = {name: build() for name in ("alice", "bob", "carol")}
    for name, c in clients.items():
        c.post("/register", json={"username": name, "password": "s3cretpw!", "email": name + "@ex.com"})
        c.post("/login", json={"username": name, "password": "s3cretpw!"})

    mid = clients["alice"].post("/media",
                                data={"file": (io.BytesIO(b"\x89PNGdm"), "d.png", "image/png")}).get_json()["id"]
    clients["alice"].post("/messages/bob/attachments", json={"attachment_ids": [mid]})

    assert clients["bob"].get(f"/media/{mid}").status_code == 200      # participant
    assert clients["carol"].get(f"/media/{mid}").status_code == 403    # outsider


def test_json_body_cap_is_untouched_by_media_override(media_client):
    # the per-request media cap must not leak: /register still enforces the 64 KB MAX_CONTENT_LENGTH.
    pad = "x" * (64 * 1024 + 1)
    r = media_client.post("/register",
                          json={"username": "u", "password": "s3cretpw!", "email": "u@ex.com", "pad": pad})
    assert r.status_code == 413
