"""Dashboard route — current state + plan + calories + history. OWNER: Lior.

Pulls the assessment via `services/ai_client` and history via `services/db`. Implement behind this URL.
"""
from flask import Blueprint, jsonify

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/dashboard")
def dashboard():
    return jsonify(detail="dashboard not implemented yet"), 501
