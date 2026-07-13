"""Daily check-in route — POST /checkin (gated). OWNER: Lior (F3 input).

The athlete logs today's recovery/readiness metrics; the web tier forwards them (with profile context)
to the ai container's ``/predict`` and records the assessment in ``analysis_history`` — so the dashboard
and ``/history`` reflect it. Fault-tolerant: if the ai container is down the check-in is still saved
(assessment unavailable), never a crash.

The metric set is the proposal's candidate daily features (PROPOSAL-v2 §5 — "the final feature set will
be determined during data exploration and may change"). To add/remove/retune a metric, edit
``CHECKIN_FIELDS`` only — the validation, the API contract, and the form all derive from it.
"""
import datetime
import logging
import math

from flask import Blueprint, current_app, jsonify, request, session

from routes.auth import login_required
from services import ai_client

logger = logging.getLogger(__name__)

checkin_bp = Blueprint("checkin", __name__)

# (name, low, high, integer) — the daily readiness inputs. Single source of truth; change here only.
CHECKIN_FIELDS = [
    ("sleep_hours", 1, 24, False),   # min 1 (not 0): the ai model's validator requires sleep_hours >= 1
    ("resting_hr", 30, 220, True),
    ("fatigue", 1, 10, True),
    ("soreness", 1, 10, True),
    ("training_load", 0, 10, True),
]


def validate_checkin(data):
    """Return a clean metrics dict for a well-formed daily check-in, else raise ``ValueError``.

    Every field is required and must be a number (bools rejected — they're an ``int`` subclass) in
    range. Non-primitive values (injection objects) are rejected here, before any query or AI call.
    """
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    clean = {}
    for name, lo, hi, integer in CHECKIN_FIELDS:
        value = data.get(name)
        allowed = int if integer else (int, float)
        if isinstance(value, bool) or not isinstance(value, allowed):
            raise ValueError(f"{name} must be a number")
        if not math.isfinite(value):                 # explicit: reject NaN/Infinity (don't rely on the range bound alone)
            raise ValueError(f"{name} must be a finite number")
        if not lo <= value <= hi:
            raise ValueError(f"{name} must be between {lo} and {hi}")
        clean[name] = value
    return clean


@checkin_bp.post("/checkin")
@login_required
def checkin():
    try:
        metrics = validate_checkin(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    username = session["username"]
    try:
        profile = current_app.config["PROFILES"].get(username)
    except Exception:
        logger.exception("profile store unavailable on check-in")
        return jsonify(error="profile store unavailable"), 503

    # readiness is assessed from today's metrics + the profile context; degrade if the ai is down.
    prediction = ai_client.predict(current_app.config["AI_URL"], {**(profile or {}), **metrics},
                                   timeout=current_app.config["AI_CLIENT_TIMEOUT"])
    ok = isinstance(prediction, dict)
    # calories is persisted to history AND returned to the client, so guard it to a finite number: a
    # non-finite AI value (NaN/Infinity) would both corrupt the stored entry and serialise as an
    # invalid-JSON token — mirrors the math.isfinite guard validate_checkin applies to user input.
    calories = prediction.get("calories") if ok else None
    if not (isinstance(calories, (int, float)) and not isinstance(calories, bool) and math.isfinite(calories)):
        calories = None
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "metrics": metrics,
        "assessment": prediction.get("state") if ok else None,
        "calories": calories,
    }

    try:
        current_app.config["HISTORY"].add(username, entry)
    except Exception:
        logger.exception("history store unavailable on check-in")
        return jsonify(error="history store unavailable"), 503

    return jsonify(entry=entry, ai_status="ok" if ok else "unavailable"), 201
