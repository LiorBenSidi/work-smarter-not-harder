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
from werkzeug.exceptions import NotFound

from ratelimit import limiter
from routes.auth import login_required
from services.media_store import stored_name

logger = logging.getLogger(__name__)

media_bp = Blueprint("media", __name__)

# The MIME -> extension map and the `<media_id><ext>` convention live in services/media_store.py, so
# upload, serve and the #507 owner-purge all resolve a blob's filename the same way.


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


def _attachment_ids(data, key="attachment_ids"):
    """Return the list of string ids under ``key``, else None (invalid).

    Shared by the attach routes (``attachment_ids``) and the batch comment read (``comment_ids``): the
    list-of-strings check is the NoSQL-injection gate for both, since these ids reach a query."""
    if not isinstance(data, dict):
        return None
    ids = data.get(key)
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
    stored = stored_name(media_id, file.mimetype)
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
    stored = stored_name(media_id, rec["mime"])
    try:
        # Explicit download_name so a saved attachment keeps its extension (#338 item 6) — don't rely on
        # Werkzeug's implicit filename, which a version bump could drop. Stays `inline` (mimetype set), so
        # <img>/<video> still render in-page; the id keeps the name unique + traceable.
        return send_from_directory(_media_root(), stored, mimetype=rec["mime"], download_name=stored)
    except NotFound:
        # The record exists but the blob is gone from the volume (rotated/lost). Return the same clean JSON
        # 404 as an unknown id (#338 item 7) and log it — a bound record with no file is an operational signal.
        logger.warning("media %s has a record but no file on disk (lost/rotated volume?)", media_id)
        return jsonify(error="not found"), 404


def _attach(target_type, target_id, peers=None):
    ids = _attachment_ids(request.get_json(silent=True))
    if ids is None:
        return jsonify(error="attachment_ids must be a list of ids"), 400
    me = session["username"]
    # #331: cap how many blobs one target can carry, so its serve read (list_for_target) stays bounded.
    # Counted against what's already bound there (the cap is on the target, not this single call), so a
    # flood spread over many calls can't grow it past the limit either. Blobs past the cap are shed.
    cap = current_app.config.get("MEDIA_MAX_ATTACHMENTS_PER_TARGET", 50)
    count = len(_media().list_for_target(target_type, target_id))
    bound = []
    for i in ids:
        if count >= cap:
            break
        if _media().bind(i, me, target_type, target_id, peers=peers):
            bound.append(i)
            count += 1
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


def _comment_key(post_id, comment_id):
    """Canonical target id for a comment's attachments.

    Scoped by BOTH ids, so a comment's blobs can never be reached through a different post — the same
    reason ``forum_get_comment`` matches on both. Comment ids are globally unique, so the post id is
    belt-and-braces rather than load-bearing, but it keeps the stored target self-describing.
    """
    return f"{post_id}:{comment_id}"


@media_bp.post("/forum/posts/<post_id>/comments/<comment_id>/attachments")
@login_required
def attach_to_comment(post_id, comment_id):
    # TA Online-Forum sub-requirement #2: "Each comment should have a body, and the option to add images
    # and videos to the comment as well." The store and `_can_view` already understood a "comment" target
    # (#338) — but nothing ever WROTE one, so that branch was dead code and the feature only LOOKED wired
    # while four documents claimed it worked (#407).
    #
    # Author-gated exactly like attach_to_post: without it any logged-in user could bolt their blob onto
    # anyone's comment. `get_comment` matches on both ids and returns the real author (anonymity is a
    # display projection), so it is the right gate even on an anonymous post.
    comment = _forum().get_comment(post_id, comment_id)
    if comment is None:
        return jsonify(error="no such comment"), 404
    if comment.get("author") != session["username"]:
        return jsonify(error="only the author can attach media to this comment"), 403
    return _attach("comment", _comment_key(post_id, comment_id))


@media_bp.get("/forum/posts/<post_id>/comments/<comment_id>/attachments")
@login_required
def list_comment_attachments(post_id, comment_id):
    # Readable by any logged-in user, mirroring the post route: the forum is public, and `_can_view`
    # already treats a "comment" target as forum content.
    return _list("comment", _comment_key(post_id, comment_id))


@media_bp.post("/forum/posts/<post_id>/comments/attachments")
@login_required
def list_many_comment_attachments(post_id):
    """Attachments for MANY comments of one post, in a single request (#407).

    A POST because it carries a list of ids, not because it writes anything — nothing here mutates.
    The per-comment GET above still exists and is still the simplest thing to reason about, but calling
    it once per comment made the page issue up to 50 parallel requests (COMMENT_PAGE_DEFAULT) against a
    browser limit of ~6 connections per origin, so unrelated requests — the forum feed among them —
    queued behind the burst. Measured on the running app: opening a post with 20 comments produced 20
    requests; it now produces one.

    Returns ``{"attachments": {comment_id: [...]}}`` keyed by COMMENT id (not the internal target id),
    so the client never has to know how a comment target is composed.
    """
    ids = _attachment_ids(request.get_json(silent=True), key="comment_ids")
    if ids is None:
        return jsonify(error="comment_ids must be a list of ids"), 400
    grouped = _media().list_for_targets("comment", [_comment_key(post_id, c) for c in ids])
    out = {}
    for comment_id in ids:
        recs = grouped.get(_comment_key(post_id, comment_id)) or []
        if recs:
            out[comment_id] = [{"id": r["id"], "url": f"/media/{r['id']}", "mime": r["mime"],
                                "owner": r.get("owner"), "created_at": r.get("created_at", 0)}
                               for r in sorted(recs, key=lambda r: r.get("created_at", 0))]
    return jsonify(attachments=out), 200


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
