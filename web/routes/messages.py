"""Direct messages + notifications — the social layer's private channel and its notification feed.

OWNER: Lior (see docs/COLLABORATORS.md). Real-time delivery is a **Server-Sent Events** push
(``GET /events`` streams ``text/event-stream``): the browser holds one ``EventSource`` open and the server
pushes a "notify" ping whenever the user has a new notification, so the client refreshes with no polling
(a slow poll remains only as a fallback). SSE is dependency-free (a streaming Flask response) and fits a
server->client feed; the client still SENDS over normal POSTs, so no bidirectional WebSocket is needed. A
connection holds a worker thread for its (capped) lifetime — fine for the demo on threaded workers; for
large scale, gevent/eventlet workers are the upgrade. Every endpoint is auth-gated; a conversation is readable ONLY by its two
participants (the thread id is derived from the caller + peer, so you can't name someone else's thread);
sending is rate-limited (anti-spam, Noam's Online-Forum §10). The stores are injected (the web->db seam:
``app.config["MESSAGES"]`` / ``["NOTIFICATIONS"]``), so this layer unit-tests with in-memory fakes.
"""
import logging
import math
import os
import threading
import time
from collections import deque

from flask import Blueprint, Response, current_app, jsonify, request, session

from routes.auth import login_required
from services.identity import display_name, display_names

logger = logging.getLogger(__name__)

messages_bp = Blueprint("messages", __name__)

BODY_MAX = 2000
RATE_WINDOW_SECONDS = 60
RATE_MAX_PER_WINDOW = 20        # a real person doesn't send 20 DMs a minute; a spammer does

# --- directory search (DM picker) ---
SEARCH_MIN_CHARS = 2           # no browsing the whole directory one letter at a time
SEARCH_MAX_RESULTS = 8         # a short, capped result set — not a user dump
SEARCH_RATE_WINDOW_SECONDS = 10.0
SEARCH_RATE_MAX = 40           # generous for debounced typing; trips only on scripted enumeration
_search_hits = {}              # username -> deque[timestamps]: best-effort per-WORKER anti-enumeration throttle
_search_hits_lock = threading.Lock()


def _search_rate_ok(user):
    """Best-effort per-worker sliding-window throttle on directory search (blunts scripted enumeration).

    Not a cross-worker guarantee — the substantive privacy guards are the >=2-char minimum, the capped
    result set, and returning only public fields. Bounded memory: the map is cleared if it ever grows
    past a cap (cheap, and only happens under a flood).
    """
    now = time.time()
    with _search_hits_lock:
        if len(_search_hits) > 1024:
            _search_hits.clear()
        dq = _search_hits.setdefault(user, deque())
        cutoff = now - SEARCH_RATE_WINDOW_SECONDS
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= SEARCH_RATE_MAX:
            return False
        dq.append(now)
        return True


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
            _notifications().add(recipient, "dm", me, me, f"New message from {display_name(me)}")
        except Exception:
            logger.warning("could not create DM notification for %s", recipient, exc_info=True)
    except Exception:
        logger.exception("message store unavailable during send")
        return jsonify(error="messaging is unavailable right now"), 503
    return jsonify(status="sent", message=message), 201


@messages_bp.get("/users/search")
@login_required
def search_users_route():
    """Directory search for the DM picker: up to ``SEARCH_MAX_RESULTS`` ``{username, display_name}`` for a
    >=2-char query. The caller is excluded; only public fields are ever returned (never email). A too-short
    query gets an empty list (200), not an error, so the autocomplete can call this on every keystroke.
    """
    me = session["username"]
    q = request.args.get("q", "")
    q = q.strip() if isinstance(q, str) else ""
    if len(q) < SEARCH_MIN_CHARS:
        return jsonify(results=[]), 200          # too short -> nothing (not an error; keystroke-driven)
    if not _search_rate_ok(me):
        return jsonify(error="you're searching too fast — take a breath"), 429
    try:
        results = _users().search(q, SEARCH_MAX_RESULTS, exclude=me)
    except Exception:
        logger.exception("user store unavailable during search")
        return jsonify(error="search is unavailable right now"), 503
    return jsonify(results=results), 200


@messages_bp.get("/conversations")
@login_required
def list_conversations():
    me = session["username"]
    try:
        convos = _messages().list_conversations(me)
        names = display_names([c["peer"] for c in convos])   # resolve all peers in one pass
        for c in convos:
            c["peer_name"] = names.get(c["peer"], c["peer"])  # shown name; c["peer"] stays the handle (addressing)
        return jsonify(conversations=convos), 200
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
    return jsonify(peer=peer, peer_name=display_name(peer), messages=thread), 200


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
    names = display_names([n.get("actor") for n in items])    # resolve actors -> shown names in one pass
    for n in items:
        n["actor"] = names.get(n.get("actor"), n.get("actor"))  # show the display name, never the internal handle
    unread = sum(1 for n in items if not n.get("read"))
    return jsonify(notifications=items, unread=unread), 200


@messages_bp.post("/notifications/read")
@login_required
def mark_notifications_read():
    me = session["username"]
    data = request.get_json(silent=True) or {}
    ids = data.get("ids")
    if ids is not None and (not isinstance(ids, list) or not all(isinstance(i, str) for i in ids)):
        return jsonify(error="ids must be a list of strings"), 400   # a non-string element would 500 in the store
    try:
        _notifications().mark_read(me, ids)
    except Exception:
        logger.exception("notification store unavailable during mark-read")
        return jsonify(error="notifications are unavailable right now"), 503
    return jsonify(status="ok"), 200


# ---- Server-Sent Events push (real-time, no polling on the client) ----
# Each open stream holds one gthread worker thread for its whole lifetime. To stop a burst of streams
# from starving the pool (gunicorn 2 workers x 4 threads = 8 slots), we (a) recycle each stream after
# EVENTS_MAX_SECONDS so slots free up, and (b) cap concurrent streams PER WORKER at EVENTS_MAX_STREAMS,
# keeping >=1 thread per worker free for ordinary requests. Over the cap, the client is told to reconnect
# later and rides its polling backstop -> NO thread is held, so /login, /health, etc. can never starve.
# (gevent/eventlet workers would lift the cap, at the cost of a new dependency — not needed for the demo.)
def _events_int_env(name, default):
    try:
        return max(1, int(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default

EVENTS_MAX_SECONDS = _events_int_env("EVENTS_MAX_SECONDS", 90)   # recycle each stream; browser auto-reconnects
EVENTS_TICK_SECONDS = 1.5                                        # how often the server checks for new notifications
EVENTS_MAX_STREAMS = _events_int_env("EVENTS_MAX_STREAMS", 3)    # per worker; keep < gunicorn --threads (reserve >=1)
_sse_slots = threading.BoundedSemaphore(EVENTS_MAX_STREAMS)     # bounds concurrent /events streams in THIS worker


@messages_bp.get("/events")
@login_required
def events():
    """Stream a `notify` ping whenever the signed-in user gets a new notification. The client holds one
    EventSource open and re-fetches on each ping — no client polling. Auth-gated like every other route.

    Concurrency guard: take one of this worker's EVENTS_MAX_STREAMS slots first; if the worker is at
    capacity, return immediately with a longer reconnect delay (holding NO thread) so ordinary requests
    always keep a free thread. The client's poll backstop covers real-time while it waits to reconnect."""
    me = session["username"]
    notifications = _notifications()

    if not _sse_slots.acquire(blocking=False):
        # This worker is at its SSE cap: don't pin a thread. Tell the browser to reconnect in 60s; its
        # poll backstop keeps notifications flowing meanwhile, and a slot frees within EVENTS_MAX_SECONDS.
        logger.info("SSE at capacity (%d/worker) — client falls back to polling", EVENTS_MAX_STREAMS)
        return Response("retry: 60000\n\n", mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    def stream():
        try:
            yield "retry: 3000\n\n"                        # browser reconnect delay after a drop
            cursor = time.time()                           # only ping on notifications created after the stream opened
            deadline = time.time() + EVENTS_MAX_SECONDS
            while time.time() < deadline:
                try:
                    fresh = notifications.list(me, since=cursor)
                except Exception:
                    logger.warning("notification store unavailable during SSE stream", exc_info=True)
                    yield ": store-unavailable\n\n"
                    time.sleep(2)
                    continue
                if fresh:
                    cursor = max(n["created_at"] for n in fresh)
                    yield "event: notify\ndata: {}\n\n"    # a change ping; the client re-fetches via the normal endpoints
                else:
                    yield ": keepalive\n\n"                 # comment line keeps the connection warm through proxies
                time.sleep(EVENTS_TICK_SECONDS)
        finally:
            _sse_slots.release()                           # free the slot on completion OR client disconnect (GeneratorExit)

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"})
