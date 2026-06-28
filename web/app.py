"""Web container — the ONLY user-facing service. OWNER: Lior (auth + dashboard + frontend).

App-factory that registers the route blueprints. `/health` is live; auth (F1), profile (F2) and
the dashboard (F7) are implemented.
"""
import logging
import secrets

from flask import Flask, jsonify, render_template

from config import Config
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.profile import profile_bp

logger = logging.getLogger(__name__)


class _DbUsers:
    """Default user store — delegates to the data layer (services/db.py, owned by Elad).

    The web->db seam Elad implements: ``get_user(db, username) -> record | None`` and
    ``create_user(db, username, password_hash) -> bool``. Resolved lazily so the web app boots and
    ``/health`` works before the DB layer lands; unit tests inject an in-memory store instead.
    """

    def __init__(self, app):
        self._app = app

    def _resolve(self):
        from services import db as db_module
        return db_module, db_module.get_db(self._app.config["MONGO_URI"])

    def get(self, username):
        db_module, handle = self._resolve()
        return db_module.get_user(handle, username)

    def add(self, username, password_hash):
        db_module, handle = self._resolve()
        return db_module.create_user(handle, username, password_hash)


class _DbProfiles:
    """Default profile store — delegates to the data layer (services/db.py, owned by Elad).

    The web->db seam Elad implements: ``get_profile(db, username) -> record | None`` and
    ``save_profile(db, username, profile)``. Resolved lazily (same rationale as _DbUsers).
    """

    def __init__(self, app):
        self._app = app

    def _resolve(self):
        from services import db as db_module
        return db_module, db_module.get_db(self._app.config["MONGO_URI"])

    def get(self, username):
        db_module, handle = self._resolve()
        return db_module.get_profile(handle, username)

    def save(self, username, profile):
        db_module, handle = self._resolve()
        return db_module.save_profile(handle, username, profile)


def create_app(config=Config, *, users=None, profiles=None):
    app = Flask(__name__)
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

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(dashboard_bp)

    @app.get("/")
    def index():
        return render_template("index.html")

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="web")

    return app
