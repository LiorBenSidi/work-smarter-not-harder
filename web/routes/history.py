"""History route — GET /history (gated). OWNER: Lior (F8 route + the db side).

Returns the current user's past analyses (analysis_history — DESIGN §2). Read-only; entries are
written when a readiness analysis is saved (the check-in flow). The history store is injected
(``app.config["HISTORY"]`` — the web->db seam: ``.list``).
"""
import logging

from flask import Blueprint, current_app, jsonify, session

from routes.auth import login_required
from services.db import HISTORY_VIEW_CAP

logger = logging.getLogger(__name__)

history_bp = Blueprint("history", __name__)


@history_bp.get("/history")
@login_required
def history():
    try:
        # Bounded read (#331): the view gets the newest HISTORY_VIEW_CAP check-ins (heatmap/trend/streak all
        # live inside it). The GDPR export calls .list() with no cap when it legitimately needs everything.
        entries = current_app.config["HISTORY"].list(session["username"], limit=HISTORY_VIEW_CAP)
    except Exception:
        logger.exception("history store unavailable")
        return jsonify(error="history store unavailable"), 503
    return jsonify(history=list(entries)), 200
