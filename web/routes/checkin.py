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

from ratelimit import limiter
from routes.auth import login_required
from services import ai_client
from services.db import HISTORY_VIEW_CAP

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
@limiter.limit("30 per minute")   # fairness cap: check-in hits the ai queue; 30/min is far above any human's
@login_required                   # daily use but stops one client hogging predictions (queue 503 is the real backstop)
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
    # Persist the per-state confidence too, so History can show the SAME real 0-100 readiness score the
    # dashboard shows (issue: History was falling back to the band level 100/66/33 because only the state
    # word was stored). Finite numbers only — a NaN/Infinity proba would corrupt the entry + serialise as
    # invalid JSON (mirrors the calories + dashboard guards). Absent/garbage -> None (History band-centres it).
    proba_raw = prediction.get("proba") if ok else None
    proba = ({str(k): float(v) for k, v in proba_raw.items()
              if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)}
             if isinstance(proba_raw, dict) else None)
    # Persist the recommendations generated for THIS check-in (#354), so History's per-entry detail view can
    # show what was advised at the time — they already ride the same /predict response, so this adds no AI call.
    # Coerce to a bounded list of strings (the ai is semi-trusted; the client also escapes on render). Entries
    # stored before this change simply have no `recommendations` key -> the detail view degrades gracefully.
    recs_raw = prediction.get("recommendations") if ok else None
    recommendations = [str(x) for x in recs_raw[:10]] if isinstance(recs_raw, list) else []
    entry = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "metrics": metrics,
        "assessment": prediction.get("state") if ok else None,
        "proba": proba,
        "calories": calories,
        "recommendations": recommendations,
    }

    try:
        current_app.config["HISTORY"].add(username, entry)
    except Exception:
        logger.exception("history store unavailable on check-in")
        return jsonify(error="history store unavailable"), 503

    return jsonify(entry=entry, ai_status="ok" if ok else "unavailable"), 201


@checkin_bp.post("/history/recommendations")
@limiter.limit("30 per minute")   # occasional (only when a pre-#354 detail opens); the cap is anti-abuse
@login_required
def regenerate_recommendations():
    """Recompute + persist the recommendations for ONE past check-in from its stored inputs (#354 backfill).

    Pre-#354 check-ins were saved before recommendations were persisted. When the detail view opens such an
    entry it calls this: we re-run /predict from the entry's OWN metrics (deterministic on metrics+state), store
    the result, and return it. Idempotent — an entry that already has recommendations is returned without an AI
    call. Scoped to the caller's own history (the timestamp only ever matches one of their rows).
    """
    data = request.get_json(silent=True) or {}
    ts = data.get("timestamp")
    if not isinstance(ts, str) or not ts:
        return jsonify(error="timestamp is required"), 400

    username = session["username"]
    try:
        entries = current_app.config["HISTORY"].list(username, limit=HISTORY_VIEW_CAP)   # the entry is in the recent view
    except Exception:
        logger.exception("history store unavailable during recommendation backfill")
        return jsonify(error="history store unavailable"), 503
    entry = next((e for e in entries if isinstance(e, dict) and e.get("timestamp") == ts), None)
    if entry is None:
        return jsonify(error="check-in not found"), 404
    if isinstance(entry.get("recommendations"), list):
        return jsonify(recommendations=entry["recommendations"]), 200    # already backfilled -> no AI call

    metrics = entry.get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        return jsonify(recommendations=[]), 200                          # no inputs to regenerate from

    try:
        profile = current_app.config["PROFILES"].get(username)
    except Exception:
        profile = None
    prediction = ai_client.predict(current_app.config["AI_URL"], {**(profile or {}), **metrics},
                                   timeout=current_app.config["AI_CLIENT_TIMEOUT"])
    if not isinstance(prediction, dict):
        return jsonify(error="ai unavailable"), 503                      # can't regenerate right now; client keeps the note
    recs_raw = prediction.get("recommendations")
    recommendations = [str(x) for x in recs_raw[:10]] if isinstance(recs_raw, list) else []
    try:
        current_app.config["HISTORY"].set_recommendations(username, ts, recommendations)
    except Exception:
        logger.exception("history store unavailable persisting regenerated recommendations")
        # non-fatal: still return the freshly-generated recs so the user sees them this session
    return jsonify(recommendations=recommendations), 200
