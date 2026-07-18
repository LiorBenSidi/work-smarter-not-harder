"""Web container — the ONLY user-facing service. OWNER: Lior (auth + dashboard + frontend).

App-factory that registers the route blueprints. `/health` is live; auth (F1), profile (F2),
the dashboard (F7), history (F8) and the forum are implemented.
"""
import hashlib
import logging
import os
import secrets
import time

from flask import Flask, g, jsonify, render_template, request, send_from_directory
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from config import Config
from csrf import init_csrf
from perf import init_perf
from ratelimit import init_limiter
from routes.auth import auth_bp
from routes.checkin import checkin_bp
from routes.dashboard import dashboard_bp
from routes.forum import forum_bp
from routes.history import history_bp
from routes.media import media_bp
from routes.messages import messages_bp
from routes.profile import profile_bp
from services.media_store import DbMedia

logger = logging.getLogger(__name__)

_TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")
_STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")


class _DbStore:
    """Base for the db.py-backed stores (owned by Lior). Lazily resolves ``(db module, handle)`` from
    the app's MONGO_URI, so the web app boots and ``/health`` works before the DB layer lands; unit
    tests inject in-memory fakes instead. Subclasses just call the seam functions on the handle.
    """

    def __init__(self, app):
        self._app = app

    def _resolve(self):
        from services import db as db_module
        return db_module, db_module.get_db(self._app.config["MONGO_URI"])


class _DbUsers(_DbStore):
    """Seam: ``get_user`` / ``create_user`` / ``get_user_by_email`` / ``update_password`` /
    ``update_display_name`` + the login-OTP challenge
    (``set_otp`` / ``get_otp`` / ``clear_otp`` / ``bump_otp_attempts``)."""

    def get(self, username):
        db_module, handle = self._resolve()
        return db_module.get_user(handle, username)

    def add(self, username, password_hash, email=None, display_name=None):
        db_module, handle = self._resolve()
        return db_module.create_user(handle, username, password_hash, email, display_name)

    def by_email(self, email):
        db_module, handle = self._resolve()
        return db_module.get_user_by_email(handle, email)

    def set_password(self, username, password_hash):
        db_module, handle = self._resolve()
        return db_module.update_password(handle, username, password_hash)

    def set_display_name(self, username, display_name):
        db_module, handle = self._resolve()
        return db_module.update_display_name(handle, username, display_name)

    def delete(self, username):
        db_module, handle = self._resolve()
        return db_module.delete_user(handle, username)

    def get_email_consent(self, username):
        db_module, handle = self._resolve()
        return db_module.get_email_consent(handle, username)

    def set_email_consent(self, username, consent):
        db_module, handle = self._resolve()
        return db_module.set_email_consent(handle, username, consent)

    def set_otp(self, username, otp_hash, expires_at):
        db_module, handle = self._resolve()
        return db_module.set_otp(handle, username, otp_hash, expires_at)

    def get_otp(self, username):
        db_module, handle = self._resolve()
        return db_module.get_otp(handle, username)

    def clear_otp(self, username):
        db_module, handle = self._resolve()
        db_module.clear_otp(handle, username)

    def bump_otp_attempts(self, username):
        db_module, handle = self._resolve()
        return db_module.bump_otp_attempts(handle, username)

    def search(self, query, limit=8, exclude=None):
        db_module, handle = self._resolve()
        return db_module.search_users(handle, query, limit, exclude)


class _DbProfiles(_DbStore):
    """Seam Lior implements: ``get_profile(db, username)`` / ``save_profile(db, username, profile)``."""

    def get(self, username):
        db_module, handle = self._resolve()
        return db_module.get_profile(handle, username)

    def save(self, username, profile):
        db_module, handle = self._resolve()
        return db_module.save_profile(handle, username, profile)

    def delete(self, username):
        db_module, handle = self._resolve()
        db_module.delete_profile(handle, username)


class _DbHistory(_DbStore):
    """Seam fns: ``list_history(db, username) -> list`` / ``add_history(db, username, entry)``."""

    def list(self, username, limit=None):
        db_module, handle = self._resolve()
        return db_module.list_history(handle, username, limit=limit)

    def add(self, username, entry):
        db_module, handle = self._resolve()
        db_module.add_history(handle, username, entry)

    def set_recommendations(self, username, timestamp, recommendations):
        db_module, handle = self._resolve()
        return db_module.history_set_recommendations(handle, username, timestamp, recommendations)

    def delete(self, username):
        db_module, handle = self._resolve()
        db_module.delete_history(handle, username)


class _DbForum(_DbStore):
    """Seam Lior implements: ``forum_create_post(db, author, title, body, anonymous)``,
    ``forum_list_posts(db)``, ``forum_get_post(db, post_id)``,
    ``forum_add_comment(db, post_id, author, body)``,
    ``forum_list_comments(db, post_id, before, limit)`` (comments live in their own collection, #331),
    ``forum_get_comment(db, post_id, comment_id)``, ``forum_vote(db, post_id, username, value)``,
    ``forum_vote_comment(db, post_id, comment_id, username, value)``."""

    def create_post(self, author, title, body, anonymous):
        db_module, handle = self._resolve()
        return db_module.forum_create_post(handle, author, title, body, anonymous)

    def list_posts(self, before=None, limit=None):
        db_module, handle = self._resolve()
        return db_module.forum_list_posts(handle, before=before, limit=limit)

    def get_post(self, post_id):
        db_module, handle = self._resolve()
        return db_module.forum_get_post(handle, post_id)

    def add_comment(self, post_id, author, body):
        db_module, handle = self._resolve()
        return db_module.forum_add_comment(handle, post_id, author, body)

    def list_comments(self, post_id, before=None, limit=None):
        db_module, handle = self._resolve()
        return db_module.forum_list_comments(handle, post_id, before=before, limit=limit)

    def get_comment(self, post_id, comment_id):
        db_module, handle = self._resolve()
        return db_module.forum_get_comment(handle, post_id, comment_id)

    def vote(self, post_id, username, value):
        db_module, handle = self._resolve()
        return db_module.forum_vote(handle, post_id, username, value)

    def vote_comment(self, post_id, comment_id, username, value):
        db_module, handle = self._resolve()
        return db_module.forum_vote_comment(handle, post_id, comment_id, username, value)

    def received_engagement(self, username):
        db_module, handle = self._resolve()
        return db_module.forum_received_engagement(handle, username)

    def update_post(self, post_id, username, title, body):
        db_module, handle = self._resolve()
        return db_module.forum_update_post(handle, post_id, username, title, body)

    def delete_post(self, post_id, username):
        db_module, handle = self._resolve()
        return db_module.forum_delete_post(handle, post_id, username)

    def purge_user(self, username):
        db_module, handle = self._resolve()
        db_module.forum_purge_user(handle, username)

    def export_user(self, username):
        db_module, handle = self._resolve()
        return db_module.forum_export_user(handle, username)

    def get_rev(self):
        # The forum revision the SSE stream watches (routes/messages.py). DB-backed so it broadcasts
        # across gunicorn workers; every forum mutation above bumps it in db.forum_bump_rev.
        db_module, handle = self._resolve()
        return db_module.forum_get_rev(handle)


class _DbMessages(_DbStore):
    """Seam Lior implements: ``message_send`` / ``message_list_conversation`` /
    ``message_list_conversations`` / ``message_mark_read`` / ``message_count_since``."""

    def send(self, sender, recipient, body):
        db_module, handle = self._resolve()
        return db_module.message_send(handle, sender, recipient, body)

    def list_conversation(self, user_a, user_b, before=None, limit=None):
        db_module, handle = self._resolve()
        return db_module.message_list_conversation(handle, user_a, user_b, before=before, limit=limit)

    def list_conversations(self, user, limit=None):
        db_module, handle = self._resolve()
        return db_module.message_list_conversations(handle, user, limit=limit)

    def mark_read(self, user, peer):
        db_module, handle = self._resolve()
        return db_module.message_mark_read(handle, user, peer)

    def mark_delivered(self, user):
        db_module, handle = self._resolve()
        return db_module.message_mark_delivered(handle, user)

    def count_since(self, user, since):
        db_module, handle = self._resolve()
        return db_module.message_count_since(handle, user, since)

    def delete_for_user(self, username):
        db_module, handle = self._resolve()
        db_module.message_delete_for_user(handle, username)

    def export_for_user(self, username):
        db_module, handle = self._resolve()
        return db_module.message_export_for_user(handle, username)


class _DbNotifications(_DbStore):
    """Seam Lior implements: ``notification_add`` / ``notification_list`` / ``notification_mark_read``."""

    def add(self, user, ntype, actor, ref, text):
        db_module, handle = self._resolve()
        return db_module.notification_add(handle, user, ntype, actor, ref, text)

    def list(self, user, since=None, limit=None):
        db_module, handle = self._resolve()
        return db_module.notification_list(handle, user, since, limit=limit)

    def mark_read(self, user, ids=None):
        db_module, handle = self._resolve()
        return db_module.notification_mark_read(handle, user, ids)

    def delete_for_user(self, username):
        db_module, handle = self._resolve()
        db_module.notification_delete_for_user(handle, username)


def create_app(config=Config, *, users=None, profiles=None, history=None, forum=None,
               messages=None, notifications=None, media=None):
    # Absolute template_folder + static_folder so the app renders and serves its PWA assets
    # (manifest, service worker, icons) regardless of how it's launched / imported.
    app = Flask(__name__, template_folder=_TEMPLATES, static_folder=_STATIC)
    app.config.from_object(config)

    # Deploy version = short hash of the app shell (index.html, where the whole SPA lives inline). It
    # changes exactly when the user-facing app changes, and a new container = a fresh read = a fresh
    # hash. The /sw.js route stamps it so each release ships a new service worker → the app auto-updates.
    try:
        with open(os.path.join(_TEMPLATES, "index.html"), "rb") as _idx:
            app.config["ASSET_VERSION"] = hashlib.sha256(_idx.read()).hexdigest()[:8]
    except OSError:
        app.config["ASSET_VERSION"] = "dev"

    # Behind Caddy (prod) the real client IP arrives in X-Forwarded-For; trust ONE proxy hop so the rate
    # limiter + logs key on the actual client, not Caddy's internal container IP (which would put every
    # external client in one shared bucket — brute-force isolation gone, and a single attacker could lock
    # everyone out). Safe: the web container is never published directly (only Caddy is public), so the
    # forwarded header can't be spoofed. A no-op when there's no proxy (local dev / the test client send
    # no X-Forwarded-For), so remote_addr is used unchanged there.
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    if not app.config.get("SECRET_KEY"):
        # Dev/test fallback so the app boots without a configured secret. Production sets a real
        # SECRET_KEY (compose enforces it via ${SECRET_KEY:?}); never run multi-worker prod on an
        # ephemeral key — sessions wouldn't validate across workers.
        app.config["SECRET_KEY"] = secrets.token_hex(32)
        logger.warning("SECRET_KEY not set — using an ephemeral key (set SECRET_KEY in production)")

    # Injectable data-access stores (the web->db seam). Tests inject in-memory fakes; production
    # falls back to the db.py-backed stores.
    app.config["USERS"] = users if users is not None else _DbUsers(app)
    app.config["PROFILES"] = profiles if profiles is not None else _DbProfiles(app)
    app.config["HISTORY"] = history if history is not None else _DbHistory(app)
    app.config["FORUM"] = forum if forum is not None else _DbForum(app)
    app.config["MESSAGES"] = messages if messages is not None else _DbMessages(app)
    app.config["NOTIFICATIONS"] = notifications if notifications is not None else _DbNotifications(app)
    app.config["MEDIA"] = media if media is not None else DbMedia(app)

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(checkin_bp)
    app.register_blueprint(forum_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(media_bp)

    @app.errorhandler(RecursionError)
    def _too_deeply_nested(_exc):
        # Deeply-nested JSON overflows the parser's recursion limit. `request.get_json(silent=True)`
        # swallows ValueError/BadRequest but NOT RecursionError (it's a RuntimeError), so without this it
        # would 500 on any endpoint. Treat it as the malformed input it is: 400, not a server error.
        return jsonify(error="request body is malformed or too deeply nested"), 400

    # The API contract is JSON everywhere. Without these, a raised HTTP error (a 404 on a stray path, a 405,
    # a 413 oversize upload, or a flask-limiter 429 breach) would fall through to Werkzeug's HTML page, which
    # the SPA's fetch layer can't parse (it reads {"error": ...}) — so the user sees a generic fallback
    # instead of the real reason. Map every HTTP error to the same JSON shape the hand-written errors use.
    _FRIENDLY_HTTP = {
        404: "not found",
        405: "that action isn't allowed here",
        413: "that file is too large",
        429: "you're doing that too fast — please slow down and try again",
    }

    @app.errorhandler(HTTPException)
    def _http_error_as_json(exc):
        return jsonify(error=_FRIENDLY_HTTP.get(exc.code, exc.description or exc.name)), exc.code

    @app.errorhandler(Exception)
    def _unexpected_error_as_json(exc):
        # Last-resort safety net: an unhandled exception (e.g. a disk/store failure in a route that didn't
        # wrap it) must never leak a traceback or an HTML 500 to the user. Log it WITH context here (Flask's
        # default logging is bypassed once we handle it), then return a generic JSON 500. HTTPExceptions are
        # more specific and handled above; this only catches the genuinely-unexpected.
        if isinstance(exc, HTTPException):     # belt-and-suspenders: never swallow an HTTP status into a 500
            return _http_error_as_json(exc)
        logger.exception("unhandled exception on %s %s", request.method, request.path)
        return jsonify(error="something went wrong on our end — please try again"), 500

    # Register the timer FIRST — before CSRF — so a request short-circuited by the CSRF check (403)
    # still gets a start stamp and therefore an access-log line (before_request runs in registration
    # order and stops at the first one that returns a response).
    @app.before_request
    def _start_timer():
        g._start = time.perf_counter()

    init_csrf(app)  # double-submit CSRF on all state-changing requests
    init_limiter(app)  # anti-spam / anti-brute-force rate limits on the auth routes

    @app.after_request
    def _access_log(response):
        # Per-request access log with timing (Week-9 / Lab-9.1: "logging has a cost"). Emits only when a
        # handler is configured (the container, via wsgi.py); a no-op in the test suite. NOTE: the time is
        # measured to response-object return, so it EXCLUDES a streamed body (fine here — the API returns
        # small JSON; revisit with response.call_on_close if SSE/large downloads are ever added).
        start = getattr(g, "_start", None)
        if start is not None:
            # method + path are attacker-controlled; strip CR/LF so a crafted request can't forge log
            # lines (CWE-117) in the file log / ELK, and mark truncation so a cut path isn't ambiguous.
            safe_method = request.method.replace("\r", "").replace("\n", "")[:16]
            safe_path = request.path.replace("\r", "\\r").replace("\n", "\\n")
            if len(safe_path) > 200:
                safe_path = safe_path[:200] + "…"
            logger.info("%s %s -> %s (%.1f ms)", safe_method, safe_path,
                        response.status_code, (time.perf_counter() - start) * 1000)
        return response

    # gzip + static cache headers (registered last -> runs first in the after_request chain, so the
    # access log above still times the fully-prepared, compressed response).
    init_perf(app)

    @app.get("/")
    def index():
        # Plain static shell — the SPA fetches credential bounds from /auth/config at runtime, so the
        # served HTML carries no template placeholders that could leak raw if mis-served. The one
        # conditional is control-flow, not data: the dev-tools markup is omitted when the shell is
        # rendered inside the mobile-preview iframe (?preview=1), so even a stale cached bundle can
        # never nest the dev tools recursively inside the preview (the #138 recursion).
        # No-store on the shell: a deployed UI change (e.g. a CSS/colour fix) must show on the next load,
        # not sit behind the browser's heuristic cache until a manual hard-refresh. The SW handles offline
        # separately (navigations are network-first), and static assets keep their own long cache headers.
        return render_template("index.html", preview=bool(request.args.get("preview"))), 200, \
            {"Cache-Control": "no-cache, no-store, must-revalidate"}

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="web")

    @app.get("/ready")
    def ready():
        # Readiness = liveness + a DB ping. The post-deploy gate (R7) and the external monitor target
        # THIS, not /health — so a green deploy proves the whole stack serves, not just that the web
        # process answers. /health stays trivial (course rule: it must boot without Mongo).
        try:
            from services import db as db_module
            db_module.get_db(app.config["MONGO_URI"]).command("ping")
        except Exception:
            logger.warning("readiness check failed: database not reachable", exc_info=True)
            # The 503 status CODE is the readiness signal the deploy gate + external monitor consume; the
            # component detail (which dependency is down) stays server-side in the log, not in the public
            # body, so an anonymous caller can't fingerprint internal state.
            return jsonify(status="degraded"), 503
        return jsonify(status="ready"), 200

    @app.get("/manifest.webmanifest")
    def manifest():
        # PWA manifest at the root path -> correct scope + mimetype, so the app is installable.
        return send_from_directory(app.static_folder, "manifest.webmanifest",
                                   mimetype="application/manifest+json")

    @app.get("/sw.js")
    def service_worker():
        # served from root so the service worker controls the whole app scope (not just /static).
        # Stamp __BUILD__ with the deploy's shell hash so the worker's bytes + cache name change every
        # release -> the browser installs the new worker and the app auto-updates (see registration in
        # index.html). Read fresh each request (cheap; no-cache anyway) so a hot-reloaded shell restamps.
        sw_path = os.path.join(app.static_folder, "sw.js")
        with open(sw_path, "r", encoding="utf-8") as fh:
            body = fh.read().replace("__BUILD__", app.config["ASSET_VERSION"])
        resp = app.response_class(body, mimetype="text/javascript")
        resp.headers["Service-Worker-Allowed"] = "/"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    return app
