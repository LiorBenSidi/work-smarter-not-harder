"""Account privacy & data — GDPR email-consent opt-in + data export. OWNER: Lior.

Consent defaults False (opt-in); toggling it persists and surfaces in /me + the export. Security email
(login OTP, password reset) is transactional and always sent regardless. The export returns everything
the app holds about the user as downloadable JSON — minus the password hash. Runs on the in-memory fakes.
"""
import io
import json as _json

import pytest


@pytest.fixture
def full_client(make_client, fake_users, fake_profiles, fake_history, fake_forum, fake_messages,
                fake_notifications, fake_media, tmp_path):
    # Media injected (#507): the export now carries a media section, so without a fake the read would
    # try to resolve Mongo. Throwaway MEDIA_ROOT, same as the media fixtures in conftest.
    c = make_client(fake_users, profiles=fake_profiles, history=fake_history, forum=fake_forum,
                    messages=fake_messages, notifications=fake_notifications, media=fake_media)
    c.raw.application.config["MEDIA_ROOT"] = str(tmp_path / "media")
    return c


def _register_login(client, name="alice", pw="password123"):
    client.post("/register", json={"username": name, "password": pw, "email": f"{name}@ex.com"})
    r = client.post("/login", json={"username": name, "password": pw})
    assert r.status_code == 200
    return r.get_json()["username"]


# ---- email consent ----
def test_email_consent_defaults_false_and_toggles(client):
    """Consent starts OFF and is on only because the user turned it on — an opt-out default would mail people who never agreed — and the choice persists in both directions."""
    _register_login(client)
    assert client.get("/me").get_json()["email_consent"] is False        # opt-in: off by default
    assert client.post("/account/email-consent", json={"consent": True}).status_code == 200
    assert client.get("/me").get_json()["email_consent"] is True          # persisted
    assert client.post("/account/email-consent", json={"consent": False}).status_code == 200
    assert client.get("/me").get_json()["email_consent"] is False


def test_email_consent_rejects_non_boolean(client):
    """Consent must be an explicit boolean: a truthy string or a missing field is refused rather than guessed, because guessing wrong means mailing someone who did not agree."""
    _register_login(client)
    assert client.post("/account/email-consent", json={"consent": "yes"}).status_code == 400
    assert client.post("/account/email-consent", json={}).status_code == 400


def test_email_consent_requires_auth(client):
    """Only the account holder can change their own consent, so it cannot be flipped by an anonymous request."""
    assert client.post("/account/email-consent", json={"consent": True}).status_code == 401


def test_security_email_is_sent_regardless_of_consent(make_otp_client, fake_users):
    """Security mail — a login code, a password reset — is transactional and goes out even with consent off.

    Consent governs marketing, not the messages a user needs to get back into their own account.
    """
    c = make_otp_client(fake_users)
    c.post("/register", json={"username": "alice", "password": "password123", "email": "a@ex.com"})
    assert fake_users.get_email_consent("alice") is False                 # never opted in
    r = c.post("/login", json={"username": "alice", "password": "password123"})
    assert r.get_json()["status"] == "otp_required" and r.get_json().get("dev_otp")


# ---- data export ----
def test_export_returns_all_user_data_as_a_download(full_client, fake_profiles, fake_history, fake_forum,
                                                    fake_messages, fake_notifications):
    """The export returns the seven stores it covers, as a real download, scoped to the caller alone — their own posts and comments, their votes, their messages, their notifications, and nobody else's. It does NOT cover uploaded media (#507), so this asserts what the payload contains, never that it is complete."""
    _register_login(full_client, "alice")
    fake_profiles.save("alice", {"age": 30, "goal": "maintain"})
    fake_history.add("alice", {"assessment": "Ready", "calories": 2000})
    fake_forum.create_post("alice", "My post", "body", False)
    bp = fake_forum.create_post("bob", "Bob's post", "b", False)
    fake_forum.add_comment(bp["id"], "alice", "my comment")
    fake_forum.vote(bp["id"], "alice", 1)
    fake_messages.send("alice", "bob", "hi bob")
    fake_notifications.add("alice", "dm", "bob", None, "Bob messaged you")
    full_client.post("/account/email-consent", json={"consent": True})

    r = full_client.get("/account/export")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("Content-Disposition", "")
    data = r.get_json()
    assert data["account"]["username"] == "alice" and data["account"]["email_consent"] is True
    assert data["profile"] == {"age": 30, "goal": "maintain"}
    assert len(data["history"]) == 1
    assert [p["title"] for p in data["forum"]["posts"]] == ["My post"]    # only alice's own post
    assert [c["body"] for c in data["forum"]["comments"]] == ["my comment"]
    assert len(data["forum"]["votes"]) == 1                               # her vote on bob's post
    assert len(data["messages"]) == 1 and len(data["notifications"]) == 1


def test_export_never_includes_the_password_hash(full_client):
    """The credential never appears anywhere in the export blob, so handing someone their own data does not hand over the hash of their password."""
    _register_login(full_client, "alice")
    data = full_client.get("/account/export").get_json()
    assert "password_hash" not in data["account"]
    assert "password_hash" not in _json.dumps(data)                       # nowhere in the whole blob


def test_export_requires_auth(full_client):
    """The export is gated, so a user's complete personal record cannot be fetched by an anonymous caller."""
    assert full_client.get("/account/export").status_code == 401


def test_export_includes_the_users_uploaded_media(full_client, tmp_path):
    """#507: media was the one store missing from the export, so a user who asked for their data got
    no record that their uploads existed at all. The bytes are deliberately NOT inlined — a JSON export
    can't carry a 10 MB video — but every entry carries a fetchable URL and enough metadata (type, size,
    what it's attached to) for the record to be meaningful."""
    _register_login(full_client, "alice")
    up = full_client.post("/media", data={"file": (io.BytesIO(b"\x89PNG\r\n\x1a\n"), "shot.png", "image/png")},
                          content_type="multipart/form-data")
    assert up.status_code == 201
    media_id = up.get_json()["id"]

    data = full_client.get("/account/export").get_json()

    assert [m["id"] for m in data["media"]] == [media_id]
    entry = data["media"][0]
    assert entry["url"] == f"/media/{media_id}"
    assert entry["mime"] == "image/png" and entry["size"] > 0
    assert "attached_to" in entry                       # None while unbound, "post"/"comment"/"dm" once bound


def test_export_does_not_leak_another_users_media(full_client, make_client, fake_users, fake_media, tmp_path):
    """The media section is owner-scoped like every other section of the export."""
    bob = make_client(fake_users, media=fake_media)
    bob.raw.application.config["MEDIA_ROOT"] = str(tmp_path / "media")
    _register_login(bob, "bob")
    bob.post("/media", data={"file": (io.BytesIO(b"\x89PNG\r\n\x1a\n"), "bob.png", "image/png")},
             content_type="multipart/form-data")

    _register_login(full_client, "alice")
    data = full_client.get("/account/export").get_json()

    assert data["media"] == []                          # alice uploaded nothing; bob's blob is not hers
