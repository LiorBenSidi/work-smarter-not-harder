"""Web container — the ONLY user-facing service. OWNER: Shiri (auth + dashboard + frontend).

App-factory that registers the route blueprints. `/health` is live; the feature routes are 501
stubs behind their final URLs for their owners to implement.
"""
from flask import Flask, jsonify

from config import Config
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.profile import profile_bp


def create_app(config=Config):
    app = Flask(__name__)
    app.config.from_object(config)

    app.register_blueprint(auth_bp)
    app.register_blueprint(profile_bp)
    app.register_blueprint(dashboard_bp)

    @app.get("/health")
    def health():
        return jsonify(status="ok", service="web")

    return app
