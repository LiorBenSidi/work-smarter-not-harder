"""Forum routes — posts / comments / votes (gated). OWNER: Lior (CRUD + UI).

Lior's slice of the Online Forum (+10); Elad owns the real-time push / notifications / media, Shiri
the cold-seed content. Input is validated + injection-safe before any query; the forum store is
injected (``app.config["FORUM"]`` — the web->db seam). Anonymous posts hide the author in responses.
"""
import logging

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
    return {"id": post["id"], "title": post["title"], "author": _author(post),
            "score": post["score"], "comments": len(post["comments"])}


def _detail(post):
    return {"id": post["id"], "title": post["title"], "body": post["body"], "author": _author(post),
            "score": post["score"], "comments": post["comments"]}


def _forum():
    return current_app.config["FORUM"]


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
    data = request.get_json(silent=True)
    value = data.get("value") if isinstance(data, dict) else None
    if isinstance(value, bool) or value not in (1, -1):  # exactly +1 or -1 (bool excluded)
        return jsonify(error="value must be 1 or -1"), 400
    try:
        score = _forum().vote(post_id, session["username"], value)
    except Exception:
        logger.exception("forum store unavailable")
        return jsonify(error="forum store unavailable"), 503
    if score is None:
        return jsonify(error="post not found"), 404
    return jsonify(score=score), 200
