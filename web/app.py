"""Web container — the ONLY user-facing service. OWNER: Lior (auth + dashboard + frontend).

App-factory that registers the route blueprints. `/health` is live; auth (F1), profile (F2),
the dashboard (F7), history (F8) and the forum are implemented.
"""
import logging
import os
import secrets
import time

from flask import Flask, g, jsonify, render_template, request

from config import Config
from csrf import init_csrf
from routes.auth import auth_bp
from routes.checkin import checkin_bp
from routes.dashboard import dashboard_bp
from routes.forum import forum_bp
from routes.history import history_bp
from routes.profile import profile_bp

logger = logging.getLogger(__name__)

_TEMPLATES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates")


class _DbStore:
    """Base for the db.py-backed stores (owned by Elad). Lazily resolves ``(db module, handle)`` from
    the app's MONGO_URI, so the web app boots and ``/health`` works before the DB layer lands; unit
    tests inject in-memory fakes instead. Subclasses just call the seam functions on the handle.
    """

    def __init__(self, app):
        self._app = app

    def _resolve(self):
        from services import db as db_module
        return db_module, db_module.get_db(self._app.config["MONGO_URI"])


class _DbUsers(_DbStore):
    """Seam Elad implements: ``get_user(db, username)`` / ``create_user(db, username, password_hash)``."""

    def get(self, username):
        db_module, handle = self._resolve()
        return db_module.get_user(handle, username)

    def add(self, username, password_hash):
        db_module, handle = self._resolve()
        return db_module.create_user(handle, username, password_hash)


class _DbProfiles(_DbStore):
    """Seam Elad implements: ``get_profile(db, username)`` / ``save_profile(db, username, profile)``."""

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
    """Seam Elad implements: ``forum_create_post(db, author, title, body, anonymous)``,
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


def create_app(config=Config, *, users=None, profiles=None, history=None, forum=None):
    # Absolute template_folder so the app renders regardless of how it's launched / imported.
    app = Flask(__name__, template_folder=_TEMPLATES)
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

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(checkin_bp)
    app.register_blueprint(forum_bp)

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

    @app.get("/")
    def index():
        # Plain static shell — the SPA fetches credential bounds from /auth/config at runtime, so the
        # served HTML carries no template placeholders that could leak raw if mis-served.
        return render_template("index.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="web")

    return app
