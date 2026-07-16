"""Media routes (OWNER: Elad) — upload / serve / attach for Forum posts, comments and DMs.

Bytes are written to a web-mounted volume (``MEDIA_ROOT``); the attachment index is the injected media
store (``app.config["MEDIA"]``). Binding an uploaded blob to a post / comment / DM happens here through
**additive** endpoints, so ``routes/forum.py`` and ``routes/messages.py`` are unmodified. Every route is
auth-gated (``@login_required``).

Size: the global ``MAX_CONTENT_LENGTH`` (64 KB) guards the small JSON routes and must stay small. An
upload needs a bigger cap, so ``POST /media`` raises it to ``MEDIA_MAX_BYTES`` for that request only
(Werkzeug 3.1 per-request ``request.max_content_length``); an oversize body then 413s before it's read.
Type: only the ``MEDIA_ALLOWED_MIME`` allowlist is accepted (else 400).
Flood (issue #313): ``POST /media`` is rate-limited (20/min per IP) and the volume's TOTAL bytes are
capped by ``MEDIA_MAX_TOTAL_BYTES`` (507 once full) — so an authenticated flood can't fill the disk.
Serve: an unbound blob is visible to its uploader only; a post/comment attachment to any logged-in user
(the forum is public); a DM attachment only to the two participants (mirrors the DM privacy contract).
"""
import logging
import os
import uuid

from flask import Blueprint, current_app, jsonify, request, send_from_directory, session

from ratelimit import limiter
from routes.auth import login_required

logger = logging.getLogger(__name__)

media_bp = Blueprint("media", __name__)

# Allowlisted MIME -> stored file extension. Keep in sync with the MEDIA_ALLOWED_MIME default in config.
_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
        "image/gif": ".gif", "video/mp4": ".mp4"}


def _media():
    return current_app.config["MEDIA"]


def _forum():
    return current_app.config["FORUM"]


def _allowed_mimes():
    raw = current_app.config.get("MEDIA_ALLOWED_MIME", "")
    return {m.strip() for m in raw.split(",") if m.strip()}


def _media_root():
    root = current_app.config["MEDIA_ROOT"]
    os.makedirs(root, exist_ok=True)
    return root


def _disk_usage(root):
    """Total bytes currently stored under MEDIA_ROOT (a flat dir — uploads never nest)."""
    try:
        with os.scandir(root) as entries:
            return sum(e.stat().st_size for e in entries if e.is_file())
    except OSError:                                  # unreadable/racing dir -> treat as empty, don't 500
        return 0


def _dm_key(a, b):
    """Canonical (order-independent) conversation id, so both participants resolve the same DM target."""
    return ":".join(sorted([a, b]))


def _attachment_ids(data):
    """Return a list of string media ids from ``{"attachment_ids": [...]}``, else None (invalid)."""
    if not isinstance(data, dict):
        return None
    ids = data.get("attachment_ids")
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        return None
    return ids


def _can_view(rec, me):
    target = rec.get("target_type")
    if target is None:                       # unbound -> uploader only
        return rec.get("owner") == me
    if target in ("post", "comment"):        # forum content is public to any logged-in user
        return True
    if target == "dm":                       # only the two participants
        return me in (rec.get("peers") or [])
    return False


@media_bp.before_request
def _cap_upload_size():
    # Raise the tiny global body cap to MEDIA_MAX_BYTES for the upload route ONLY, so other routes keep
    # the 64 KB JSON guard and an oversize upload 413s before the body is read.
    if request.method == "POST" and request.path == "/media":
        request.max_content_length = current_app.config["MEDIA_MAX_BYTES"]


@media_bp.post("/media")
@limiter.limit("20 per minute")   # issue #313: blunt an authenticated upload flood (mirrors the forum caps)
@login_required
def upload():
    file = request.files.get("file")
    if file is None:
        return jsonify(error="no file part named 'file'"), 400
    if file.mimetype not in _allowed_mimes():
        return jsonify(error="unsupported media type"), 400
    # Issue #313: bound the volume's TOTAL bytes, not just the per-file cap, so uploads can't fill the
    # VM's disk 10 MB at a time (a full disk wedges Mongo writes + logging). Checked before the write;
    # worst-case overshoot is one file (<= MEDIA_MAX_BYTES) — negligible against the volume-wide cap.
    if _disk_usage(_media_root()) >= current_app.config["MEDIA_MAX_TOTAL_BYTES"]:
        logger.warning("media upload rejected: MEDIA_ROOT is at/over MEDIA_MAX_TOTAL_BYTES")
        return jsonify(error="media storage is full"), 507
    media_id = uuid.uuid4().hex
    stored = media_id + _EXT.get(file.mimetype, "")
    file.save(os.path.join(_media_root(), stored))
    size = os.path.getsize(os.path.join(_media_root(), stored))
    _media().add(media_id, session["username"], file.mimetype, size)
    return jsonify(id=media_id, url=f"/media/{media_id}"), 201


@media_bp.get("/media/<media_id>")
@login_required
def serve(media_id):
    rec = _media().get(media_id)
    if rec is None:
        return jsonify(error="not found"), 404
    if not _can_view(rec, session["username"]):
        return jsonify(error="forbidden"), 403
    return send_from_directory(_media_root(), media_id + _EXT.get(rec["mime"], ""), mimetype=rec["mime"])


def _attach(target_type, target_id, peers=None):
    ids = _attachment_ids(request.get_json(silent=True))
    if ids is None:
        return jsonify(error="attachment_ids must be a list of ids"), 400
    me = session["username"]
    bound = [i for i in ids if _media().bind(i, me, target_type, target_id, peers=peers)]
    return jsonify(bound=bound), 200


def _list(target_type, target_id):
    # `owner` + `created_at` let the DM view weave each image into the message timeline (right column for
    # the sender, at the moment it was shared) instead of a separate strip. The forum grid ignores them.
    recs = _media().list_for_target(target_type, target_id)
    return jsonify(attachments=[{"id": r["id"], "url": f"/media/{r['id']}", "mime": r["mime"],
                                 "owner": r.get("owner"), "created_at": r.get("created_at", 0)}
                                for r in sorted(recs, key=lambda r: r.get("created_at", 0))]), 200


@media_bp.post("/forum/posts/<post_id>/attachments")
@login_required
def attach_to_post(post_id):
    # Only the post's author may attach media to it — and the post must exist. Without this, any logged-in
    # user could bolt their blob onto anyone's post (or a bogus id). `get_post` returns the real author even
    # for an anonymous post (anonymity is a display projection).
    post = _forum().get_post(post_id)
    if post is None:
        return jsonify(error="no such post"), 404
    if post.get("author") != session["username"]:
        return jsonify(error="only the author can attach media to this post"), 403
    return _attach("post", post_id)


@media_bp.get("/forum/posts/<post_id>/attachments")
@login_required
def list_post_attachments(post_id):
    return _list("post", post_id)


@media_bp.post("/messages/<peer>/attachments")
@login_required
def attach_to_dm(peer):
    me = session["username"]
    return _attach("dm", _dm_key(me, peer), peers=[me, peer])


@media_bp.get("/messages/<peer>/attachments")
@login_required
def list_dm_attachments(peer):
    me = session["username"]
    return _list("dm", _dm_key(me, peer))
