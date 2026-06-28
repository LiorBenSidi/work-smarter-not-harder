"""Web container — the ONLY user-facing service. OWNER: Lior (auth + dashboard + frontend).

App-factory that registers the route blueprints. `/health` is live and auth (F1) is implemented;
the remaining feature routes are 501 stubs behind their final URLs for their owners to fill in.
"""
from flask import Flask, jsonify, render_template

from config import Config
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.profile import profile_bp


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


def create_app(config=Config, *, users=None):
    app = Flask(__name__)
    app.config.from_object(config)

    # Injectable user store (the web->db seam: .get / .add). Tests inject an in-memory fake;
    # production falls back to the db.py-backed store.
    app.config["USERS"] = users if users is not None else _DbUsers(app)

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
