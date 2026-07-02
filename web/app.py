"""Web container — the ONLY user-facing service. OWNER: Lior (auth + dashboard + frontend).

App-factory that registers the route blueprints. `/health` is live; auth (F1), profile (F2),
the dashboard (F7), history (F8) and the forum are implemented.
"""
import logging
import os
import secrets
import time

from flask import Flask, g, jsonify, render_template, request, send_from_directory

from config import Config
from csrf import init_csrf
from perf import init_perf
from routes.auth import auth_bp
from routes.checkin import checkin_bp
from routes.dashboard import dashboard_bp
from routes.forum import forum_bp
from routes.history import history_bp
from routes.messages import messages_bp
from routes.profile import profile_bp

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
    """Seam: ``get_user`` / ``create_user`` / ``get_user_by_email`` / ``update_password`` +
    the login-OTP challenge (``set_otp`` / ``get_otp`` / ``clear_otp`` / ``bump_otp_attempts``)."""

    def get(self, username):
        db_module, handle = self._resolve()
        return db_module.get_user(handle, username)

    def add(self, username, password_hash, email=None):
        db_module, handle = self._resolve()
        return db_module.create_user(handle, username, password_hash, email)

    def by_email(self, email):
        db_module, handle = self._resolve()
        return db_module.get_user_by_email(handle, email)

    def set_password(self, username, password_hash):
        db_module, handle = self._resolve()
        return db_module.update_password(handle, username, password_hash)

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


class _DbProfiles(_DbStore):
    """Seam Lior implements: ``get_profile(db, username)`` / ``save_profile(db, username, profile)``."""

    def get(self, username):
        db_module, handle = self._resolve()
        return db_module.get_profile(handle, username)

    def save(self, username, profile):
        db_module, handle = self._resolve()
        return db_module.save_profile(handle, username, profile)


class _DbHistory(_DbStore):
    """Seam fns: ``list_history(db, username) -> list`` / ``add_history(db, username, entry)``."""

    def list(self, username):
        db_module, handle = self._resolve()
        return db_module.list_history(handle, username)

    def add(self, username, entry):
        db_module, handle = self._resolve()
        db_module.add_history(handle, username, entry)


class _DbForum(_DbStore):
    """Seam Lior implements: ``forum_create_post(db, author, title, body, anonymous)``,
    ``forum_list_posts(db)``, ``forum_get_post(db, post_id)``,
    ``forum_add_comment(db, post_id, author, body)``, ``forum_vote(db, post_id, username, value)``."""

    def create_post(self, author, title, body, anonymous):
        db_module, handle = self._resolve()
        return db_module.forum_create_post(handle, author, title, body, anonymous)

    def list_posts(self):
        db_module, handle = self._resolve()
        return db_module.forum_list_posts(handle)

    def get_post(self, post_id):
        db_module, handle = self._resolve()
        return db_module.forum_get_post(handle, post_id)

    def add_comment(self, post_id, author, body):
        db_module, handle = self._resolve()
        return db_module.forum_add_comment(handle, post_id, author, body)

    def vote(self, post_id, username, value):
        db_module, handle = self._resolve()
        return db_module.forum_vote(handle, post_id, username, value)

    def update_post(self, post_id, username, title, body):
        db_module, handle = self._resolve()
        return db_module.forum_update_post(handle, post_id, username, title, body)

    def delete_post(self, post_id, username):
        db_module, handle = self._resolve()
        return db_module.forum_delete_post(handle, post_id, username)


class _DbMessages(_DbStore):
    """Seam Lior implements: ``message_send`` / ``message_list_conversation`` /
    ``message_list_conversations`` / ``message_mark_read`` / ``message_count_since``."""

    def send(self, sender, recipient, body):
        db_module, handle = self._resolve()
        return db_module.message_send(handle, sender, recipient, body)

    def list_conversation(self, user_a, user_b):
        db_module, handle = self._resolve()
        return db_module.message_list_conversation(handle, user_a, user_b)

    def list_conversations(self, user):
        db_module, handle = self._resolve()
        return db_module.message_list_conversations(handle, user)

    def mark_read(self, user, peer):
        db_module, handle = self._resolve()
        return db_module.message_mark_read(handle, user, peer)

    def count_since(self, user, since):
        db_module, handle = self._resolve()
        return db_module.message_count_since(handle, user, since)


class _DbNotifications(_DbStore):
    """Seam Lior implements: ``notification_add`` / ``notification_list`` / ``notification_mark_read``."""

    def add(self, user, ntype, actor, ref, text):
        db_module, handle = self._resolve()
        return db_module.notification_add(handle, user, ntype, actor, ref, text)

    def list(self, user, since=None):
        db_module, handle = self._resolve()
        return db_module.notification_list(handle, user, since)

    def mark_read(self, user, ids=None):
        db_module, handle = self._resolve()
        return db_module.notification_mark_read(handle, user, ids)


def create_app(config=Config, *, users=None, profiles=None, history=None, forum=None,
               messages=None, notifications=None):
    # Absolute template_folder + static_folder so the app renders and serves its PWA assets
    # (manifest, service worker, icons) regardless of how it's launched / imported.
    app = Flask(__name__, template_folder=_TEMPLATES, static_folder=_STATIC)
    app.config.from_object(config)

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

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(checkin_bp)
    app.register_blueprint(forum_bp)
    app.register_blueprint(messages_bp)

    # Register the timer FIRST — before CSRF — so a request short-circuited by the CSRF check (403)
    # still gets a start stamp and therefore an access-log line (before_request runs in registration
    # order and stops at the first one that returns a response).
    @app.before_request
    def _start_timer():
        g._start = time.perf_counter()

    init_csrf(app)  # double-submit CSRF on all state-changing requests

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
        # served HTML carries no template placeholders that could leak raw if mis-served.
        return render_template("index.html")

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
            return jsonify(status="degraded", db="down"), 503
        return jsonify(status="ready", db="up"), 200

    @app.get("/manifest.webmanifest")
    def manifest():
        # PWA manifest at the root path -> correct scope + mimetype, so the app is installable.
        return send_from_directory(app.static_folder, "manifest.webmanifest",
                                   mimetype="application/manifest+json")

    @app.get("/sw.js")
    def service_worker():
        # served from root so the service worker controls the whole app scope (not just /static).
        resp = send_from_directory(app.static_folder, "sw.js", mimetype="text/javascript")
        resp.headers["Service-Worker-Allowed"] = "/"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    return app
