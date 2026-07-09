"""Dashboard route — GET /dashboard (gated). OWNER: Lior (F7).

Orchestrates the user's profile (the PROFILES store) + the ai container's readiness assessment
(`ai_client.predict` -> ai `/predict`) into one view. The ai call degrades gracefully: if the ai
container is unreachable, readiness is reported unavailable and the page must NOT crash
(fault tolerance — DESIGN §5). `calories` is read from the ai response when present.
"""
import logging
import math

from flask import Blueprint, current_app, jsonify, session

from routes.auth import login_required
from services import ai_client

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)


def _finite_number(v):
    """True iff `v` is a real finite number (int/float, not bool, not NaN/Infinity).

    The AI's numeric outputs (per-state proba, calories) flow straight into the JSON response, and
    ``jsonify`` serialises a non-finite float as the bare tokens ``NaN`` / ``Infinity`` — invalid JSON
    that a browser's ``JSON.parse`` rejects, blanking the dashboard. So a non-finite (or non-numeric)
    AI value is dropped here, mirroring the ``math.isfinite`` guard the check-in + profile validators
    already apply to user input.
    """
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


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

    prediction = ai_client.predict(current_app.config["AI_URL"], profile,
                                   timeout=current_app.config["AI_CLIENT_TIMEOUT"])
    if not isinstance(prediction, dict):
        # ai unreachable (None) or a malformed non-object response -> degrade gracefully, never crash
        return jsonify(profile=profile, readiness=None, calories=None, ai_status="unavailable"), 200

    recs = prediction.get("recommendations")
    proba = prediction.get("proba")
    readiness = {
        "state": prediction.get("state"),
        "recommendations": recs if isinstance(recs, list) else [],
        # Per-state confidence for the UI's readiness breakdown. Finite numbers only — a non-numeric OR
        # non-finite (NaN/Infinity) proba value is dropped (bool is excluded: it's an int subclass), so it
        # never reaches the response as an invalid-JSON NaN/Infinity token; None when the map is absent.
        "proba": {str(k): float(v) for k, v in proba.items()
                  if _finite_number(v)} if isinstance(proba, dict) else None,
    }
    # calories is passed straight to the client too, so it gets the same finite-number guard (a non-finite
    # AI value would otherwise serialise as an invalid-JSON `Infinity`/`NaN` token). Absent/garbage -> null.
    calories = prediction.get("calories")
    return jsonify(profile=profile, readiness=readiness,
                   calories=calories if _finite_number(calories) else None, ai_status="ok"), 200
