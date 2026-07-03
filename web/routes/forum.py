"""Forum routes — posts / comments / votes + vote notifications (gated). OWNER: Lior (CRUD + UI).

Lior's slice of the Online Forum (+10). A vote now pushes a live notification to the post's author
(§2.6) through the shared notification feed (the same feed DMs use, delivered in real time by the
SSE stream); media/attachments on posts+comments remain open, and the cold-seed content is Shiri's.
Input is validated + injection-safe before any query; the forum + notification stores are injected
(the web->db seam). Anonymous posts hide the author in responses (but the owner is still notified).
"""
import logging
import time

from flask import Blueprint, current_app, jsonify, request, session

from routes.auth import login_required

logger = logging.getLogger(__name__)

forum_bp = Blueprint("forum", __name__)

TITLE_MAX = 140
BODY_MAX = 5000
COMMENT_MAX = 2000


def validate_post(data):
    """Return ``(title, body, anonymous)`` for a well-formed post, else raise ``ValueError``."""
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    title = data.get("title")
    body = data.get("body")
    anonymous = data.get("anonymous", False)
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= TITLE_MAX:
        raise ValueError(f"title must be 1-{TITLE_MAX} characters")
    if not isinstance(body, str) or not 1 <= len(body.strip()) <= BODY_MAX:
        raise ValueError(f"body must be 1-{BODY_MAX} characters")
    if not isinstance(anonymous, bool):
        raise ValueError("anonymous must be a boolean")
    return title.strip(), body.strip(), anonymous


def validate_comment(data):
    """Return the cleaned comment body for a well-formed payload, else raise ``ValueError``."""
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    body = data.get("body")
    if not isinstance(body, str) or not 1 <= len(body.strip()) <= COMMENT_MAX:
        raise ValueError(f"body must be 1-{COMMENT_MAX} characters")
    return body.strip()


def _author(post):
    return "Anonymous" if post.get("anonymous") else post.get("author")


def _summary(post):
    # tolerate partial/seed rows from the store: a missing score/comments degrades this row to a
    # default rather than 500-ing the whole list.
    return {"id": post.get("id"), "title": post.get("title"), "author": _author(post),
            "score": post.get("score", 0), "comments": len(post.get("comments") or [])}


def _detail(post):
    return {"id": post.get("id"), "title": post.get("title"), "body": post.get("body"),
            "author": _author(post), "score": post.get("score", 0),
            "comments": post.get("comments") or []}


def _forum():
    return current_app.config["FORUM"]


def _notifications():
    return current_app.config["NOTIFICATIONS"]


# Anti-spam (§2.7): collapse repeated votes from the SAME voter on the SAME post into one ping per
# window, so toggling up/down can't flood the author's feed. A genuinely later vote (past the window)
# pings again — coalescing is time-bounded, never a permanent mute — and the bounded lookback keeps the
# check cheap (we only scan notifications newer than the cutoff, not the author's whole history).
VOTE_NOTIFY_COALESCE_SECONDS = 60


def _notify_author_of_vote(post_id, voter, value):
    """Tell a post's author their post was up/downvoted (Online-Forum §2.6, live notifications).

    Best-effort: a notification hiccup must NEVER fail the vote itself (mirrors the DM-send path). A
    self-vote is skipped, and rapid re-votes are coalesced within the window above (the score is always
    authoritative, so the ping is just "someone engaged" — it needn't track every flip). The author is
    read from the store, which keeps the REAL author even for an anonymous post — anonymity is a
    display-layer projection, so the owner is still notified about their own post.
    """
    try:
        post = _forum().get_post(post_id)
        author = post.get("author") if post else None
        if not author or author == voter:
            return
        cutoff = time.time() - VOTE_NOTIFY_COALESCE_SECONDS
        recent = any(n.get("type") == "vote" and n.get("ref") == post_id and n.get("actor") == voter
                     for n in _notifications().list(author, since=cutoff))
        if recent:
            return
        verb = "upvoted" if value == 1 else "downvoted"
        _notifications().add(author, "vote", voter, post_id, f"{voter} {verb} your post")
    except Exception:
        logger.warning("could not create a vote notification", exc_info=True)


@forum_bp.get("/forum/posts")
@login_required
def list_posts():
    try:
        posts = _forum().list_posts()
    except Exception:
        logger.exception("forum store unavailable")
        return jsonify(error="forum store unavailable"), 503
    return jsonify(posts=[_summary(p) for p in posts]), 200


@forum_bp.post("/forum/posts")
@login_required
def create_post():
    try:
        title, body, anonymous = validate_post(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    try:
        post = _forum().create_post(session["username"], title, body, anonymous)
    except Exception:
        logger.exception("forum store unavailable")
        return jsonify(error="forum store unavailable"), 503
    return jsonify(post=_detail(post)), 201


@forum_bp.get("/forum/posts/<post_id>")
@login_required
def get_post(post_id):
    try:
        post = _forum().get_post(post_id)
    except Exception:
        logger.exception("forum store unavailable")
        return jsonify(error="forum store unavailable"), 503
    if post is None:
        return jsonify(error="post not found"), 404
    return jsonify(post=_detail(post)), 200


@forum_bp.patch("/forum/posts/<post_id>")
@login_required
def edit_post(post_id):
    try:
        title, body, _ = validate_post(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    try:
        result = _forum().update_post(post_id, session["username"], title, body)
    except Exception:
        logger.exception("forum store unavailable")
        return jsonify(error="forum store unavailable"), 503
    if result is None:
        return jsonify(error="post not found"), 404
    if result == "forbidden":
        return jsonify(error="you can only edit your own post"), 403
    return jsonify(post=_detail(result)), 200


@forum_bp.delete("/forum/posts/<post_id>")
@login_required
def delete_post(post_id):
    try:
        result = _forum().delete_post(post_id, session["username"])
    except Exception:
        logger.exception("forum store unavailable")
        return jsonify(error="forum store unavailable"), 503
    if result is None:
        return jsonify(error="post not found"), 404
    if result == "forbidden":
        return jsonify(error="you can only delete your own post"), 403
    return jsonify(status="deleted"), 200


@forum_bp.post("/forum/posts/<post_id>/comments")
@login_required
def add_comment(post_id):
    try:
        body = validate_comment(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    try:
        comment = _forum().add_comment(post_id, session["username"], body)
    except Exception:
        logger.exception("forum store unavailable")
        return jsonify(error="forum store unavailable"), 503
    if comment is None:
        return jsonify(error="post not found"), 404
    return jsonify(comment=comment), 201


@forum_bp.post("/forum/posts/<post_id>/vote")
@login_required
def vote(post_id):
    voter = session["username"]
    data = request.get_json(silent=True)
    value = data.get("value") if isinstance(data, dict) else None
    if type(value) is not int or value not in (1, -1):  # exactly the ints +1 / -1 (no bool, no float)
        return jsonify(error="value must be 1 or -1"), 400
    try:
        score = _forum().vote(post_id, voter, value)
    except Exception:
        logger.exception("forum store unavailable")
        return jsonify(error="forum store unavailable"), 503
    if score is None:
        return jsonify(error="post not found"), 404
    _notify_author_of_vote(post_id, voter, value)   # live push to the author; never fails the vote
    return jsonify(score=score), 200
