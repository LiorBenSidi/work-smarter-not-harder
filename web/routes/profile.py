"""Profile route — GET/POST the athlete profile. OWNER: Shiri (route) + Elad (data layer).

The route lives in `web`; the data access is Elad's `services/db.py`. Mandatory: validate input
before any Mongo query (NoSQL-injection defense). Implement behind this URL.
"""
from flask import Blueprint, jsonify

profile_bp = Blueprint("profile", __name__)


@profile_bp.route("/profile", methods=["GET", "POST"])
def profile():
    return jsonify(detail="profile not implemented yet"), 501
