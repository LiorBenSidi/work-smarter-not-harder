"""Dashboard route — GET /dashboard (gated). OWNER: Lior (F7).

Orchestrates the user's profile (the PROFILES store) + the ai container's readiness assessment
(`ai_client.predict` -> ai `/predict`) into one view. The ai call degrades gracefully: if the ai
container is unreachable, readiness is reported unavailable and the page must NOT crash
(fault tolerance — DESIGN §5). `calories` is read from the ai response when present.
"""
import logging

from flask import Blueprint, current_app, jsonify, session

from routes.auth import login_required
from services import ai_client

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.get("/dashboard")
@login_required
def dashboard():
    try:
        profile = current_app.config["PROFILES"].get(session["username"])
    except Exception:
        logger.exception("profile store unavailable on dashboard")
        return jsonify(error="profile store unavailable"), 503

    if profile is None:
        return jsonify(profile=None, readiness=None, calories=None,
                       ai_status="skipped", needs_profile=True), 200

    prediction = ai_client.predict(current_app.config["AI_URL"], profile)
    if not isinstance(prediction, dict):
        # ai unreachable (None) or a malformed non-object response -> degrade gracefully, never crash
        return jsonify(profile=profile, readiness=None, calories=None, ai_status="unavailable"), 200

    recs = prediction.get("recommendations")
    proba = prediction.get("proba")
    readiness = {
        "state": prediction.get("state"),
        "recommendations": recs if isinstance(recs, list) else [],
        # Per-state confidence for the UI's readiness breakdown. Numbers only — a buggy/hostile AI can't
        # inject non-numeric values here (bool is excluded: it's an int subclass); None when absent.
        "proba": {str(k): float(v) for k, v in proba.items()
                  if isinstance(v, (int, float)) and not isinstance(v, bool)} if isinstance(proba, dict) else None,
    }
    return jsonify(profile=profile, readiness=readiness,
                   calories=prediction.get("calories"), ai_status="ok"), 200
