"""Web container — the ONLY user-facing service. OWNER: Lior (auth + dashboard + frontend).

App-factory that registers the route blueprints. `/health` is live; auth (F1), profile (F2),
the dashboard (F7), history (F8) and the forum are implemented.
"""
import logging
import os
import secrets

from flask import Flask, jsonify, render_template

from config import Config
from csrf import init_csrf
from routes import auth as _auth          # read credential bounds live (single source of truth)
from routes.auth import auth_bp
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
    """Seam Elad implements: ``list_history(db, username) -> list``."""

    def list(self, username):
        db_module, handle = self._resolve()
        return db_module.list_history(handle, username)


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
    app.register_blueprint(forum_bp)

    init_csrf(app)  # double-submit CSRF on all state-changing requests

    @app.get("/")
    def index():
        # Inject the validator's actual bounds so the register-form hints (tooltip / aria-label /
        # min-max / "min N chars") track auth.py, never a hardcoded duplicate.
        return render_template(
            "index.html",
            username_min=_auth.USERNAME_MIN, username_max=_auth.USERNAME_MAX,
            password_min=_auth.PASSWORD_MIN, password_max=_auth.PASSWORD_MAX,
        )

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="web")

    return app
