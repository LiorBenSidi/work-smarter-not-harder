"""Direct messages + notifications — the social layer's private channel and its notification feed.

OWNER: Lior (absorbed from Elad's real-time lane per the 2026-06-28 handoff; see docs/COLLABORATORS.md).
Real-time delivery is short-interval CLIENT polling of ``GET /notifications`` — no new dependency and no
gunicorn worker-model change (an SSE/WebSocket push would tie up a worker thread per open client; that's
the documented future upgrade). Every endpoint is auth-gated; a conversation is readable ONLY by its two
participants (the thread id is derived from the caller + peer, so you can't name someone else's thread);
sending is rate-limited (anti-spam, Noam's Online-Forum §10). The stores are injected (the web->db seam:
``app.config["MESSAGES"]`` / ``["NOTIFICATIONS"]``), so this layer unit-tests with in-memory fakes.
"""
import logging
import math
import time

from flask import Blueprint, current_app, jsonify, request, session

from routes.auth import login_required

logger = logging.getLogger(__name__)

messages_bp = Blueprint("messages", __name__)

BODY_MAX = 2000
RATE_WINDOW_SECONDS = 60
RATE_MAX_PER_WINDOW = 20        # a real person doesn't send 20 DMs a minute; a spammer does


def _messages():
    return current_app.config["MESSAGES"]


def _notifications():
    return current_app.config["NOTIFICATIONS"]


def _users():
    return current_app.config["USERS"]


def validate_dm(data):
    """Return ``(recipient, body)`` for a well-formed DM payload, else raise ``ValueError``.

    The string-type checks are the NoSQL-injection gate — a ``{"to": {"$gt": ""}}`` payload is rejected
    here, before ``to`` is ever used in a lookup.
    """
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    recipient = data.get("to")
    body = data.get("body")
    if not isinstance(recipient, str) or not recipient.strip():
        raise ValueError("a recipient is required")
    if not isinstance(body, str) or not 1 <= len(body.strip()) <= BODY_MAX:
        raise ValueError(f"message must be 1-{BODY_MAX} characters")
    return recipient.strip(), body.strip()


@messages_bp.post("/messages")
@login_required
def send_message():
    me = session["username"]
    try:
        recipient, body = validate_dm(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    if recipient == me:
        return jsonify(error="you can't message yourself"), 400
    try:
        if _users().get(recipient) is None:
            # 404 tells the sender they mistyped the recipient — a deliberate UX-over-enumeration choice:
            # usernames are already visible on forum posts, so this reveals little beyond what's public.
            return jsonify(error="no such user"), 404
        # anti-spam: cap how many messages one user can send per rolling window
        if _messages().count_since(me, time.time() - RATE_WINDOW_SECONDS) >= RATE_MAX_PER_WINDOW:
            return jsonify(error="you're sending messages too fast — take a breath"), 429
        message = _messages().send(me, recipient, body)
        # notify the recipient (best-effort — a notification hiccup must not fail the send)
        try:
            _notifications().add(recipient, "dm", me, me, f"New message from {me}")
        except Exception:
            logger.warning("could not create DM notification for %s", recipient, exc_info=True)
    except Exception:
        logger.exception("message store unavailable during send")
        return jsonify(error="messaging is unavailable right now"), 503
    return jsonify(status="sent", message=message), 201


@messages_bp.get("/conversations")
@login_required
def list_conversations():
    me = session["username"]
    try:
        return jsonify(conversations=_messages().list_conversations(me)), 200
    except Exception:
        logger.exception("message store unavailable during conversation list")
        return jsonify(error="messaging is unavailable right now"), 503


@messages_bp.get("/conversations/<peer>")
@login_required
def get_conversation(peer):
    me = session["username"]
    # Authorization by construction: the thread id is derived from {me, peer}, so this can only ever
    # return a conversation the caller is part of — there is no way to address someone else's thread.
    try:
        thread = _messages().list_conversation(me, peer)
        _messages().mark_read(me, peer)          # opening the thread clears its unread
    except Exception:
        logger.exception("message store unavailable during conversation read")
        return jsonify(error="messaging is unavailable right now"), 503
    return jsonify(peer=peer, messages=thread), 200


@messages_bp.get("/notifications")
@login_required
def list_notifications():
    me = session["username"]
    since = request.args.get("since", type=float)     # the polling cursor (epoch secs); None -> all
    if since is not None and not math.isfinite(since):
        since = None                                  # a garbage cursor (nan/inf) must not blackhole the feed
    try:
        items = _notifications().list(me, since)
    except Exception:
        logger.exception("notification store unavailable during poll")
        return jsonify(error="notifications are unavailable right now"), 503
    unread = sum(1 for n in items if not n.get("read"))
    return jsonify(notifications=items, unread=unread), 200


@messages_bp.post("/notifications/read")
@login_required
def mark_notifications_read():
    me = session["username"]
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")
    if ids is not None and not isinstance(ids, list):
        return jsonify(error="ids must be a list"), 400
    try:
        _notifications().mark_read(me, ids)
    except Exception:
        logger.exception("notification store unavailable during mark-read")
        return jsonify(error="notifications are unavailable right now"), 503
    return jsonify(status="ok"), 200
