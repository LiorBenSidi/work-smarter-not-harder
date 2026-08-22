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
from routes.profile import derive_tier
from services import ai_client
from services.db import HISTORY_VIEW_CAP

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint("dashboard", __name__)

# How many recent check-ins to forward to the AI for trend-aware recommendations. The engine only
# inspects the last few entries; a small window keeps the /predict body well within the ai container's
# limit while covering every trend rule (the longest looks back three entries).
_HISTORY_WINDOW = 10


def _finite_number(v):
    """True iff `v` is a real finite number (int/float, not bool, not NaN/Infinity).

    The AI's numeric outputs (per-state proba, calories) flow straight into the JSON response, and
    ``jsonify`` serialises a non-finite float as the bare tokens ``NaN`` / ``Infinity`` — invalid JSON
    that a browser's ``JSON.parse`` rejects, blanking the dashboard. So a non-finite (or non-numeric)
    AI value is dropped here, mirroring the ``math.isfinite`` guard the check-in + profile validators
    already apply to user input.
    """
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _workout_plan(v):
    """The AI's `plan`, or None when it is not one of the two shapes the contract allows.

    F5 returns exactly two shapes (`ai/inference.py`): a resolved plan, ``{"split": str, "days": [...]}``,
    or an ambiguous one the athlete must settle, ``{"split_options": [str, str]}`` — 4 and 5 sessions a
    week each map to two defensible splits, so the engine asks instead of guessing. Anything else is a
    contract break rather than a user-visible state, and the card renders nothing rather than half a plan.
    Same reasoning as `_finite_number`: this crosses a container boundary, so it is validated here and not
    trusted to be well-formed.
    """
    if not isinstance(v, dict):
        return None
    if isinstance(v.get("split"), str) and isinstance(v.get("days"), list):
        return {"split": v["split"], "days": v["days"]}
    options = v.get("split_options")
    if isinstance(options, list) and options and all(isinstance(o, str) for o in options):
        return {"split_options": list(options)}
    return None


@dashboard_bp.get("/dashboard")
@login_required
def dashboard():
    try:
        profile = current_app.config["PROFILES"].get(session["username"])
    except Exception:
        logger.exception("profile store unavailable on dashboard")
        return jsonify(error="profile store unavailable"), 503

    # Readiness is scored from the athlete's LATEST daily check-in metrics. The profile context is OPTIONAL
    # (issue #266): the model scores on the daily metrics alone — the profile only adds the calorie target —
    # so the dashboard must NOT gate the whole readiness view on a profile. A user who has checked in sees
    # their readiness whether or not a profile exists; `needs_profile` is a soft hint for the calorie
    # target, not a hard block. With NO check-in there's simply nothing to score (the metrics are what the
    # model needs), so we prompt a check-in — never an unscoreable profile-only /predict.
    try:
        # Bounded read (#331): the dashboard only needs the LATEST check-in (readiness) plus the newest
        # _HISTORY_WINDOW entries (trend), so cap the read at HISTORY_VIEW_CAP (newest-N, oldest-first
        # within that window) instead of loading the whole append-only log. Matches the /history route's
        # cap; the GDPR export is the only history read that legitimately stays uncapped.
        entries = list(current_app.config["HISTORY"].list(session["username"], limit=HISTORY_VIEW_CAP))
    except Exception:
        logger.exception("history store unavailable on dashboard")
        return jsonify(error="history store unavailable"), 503

    latest = entries[-1] if entries else None
    metrics = latest.get("metrics") if isinstance(latest, dict) else None
    if not isinstance(metrics, dict) or not metrics:
        # No check-in yet -> nothing to score. Prompt one, and flag a missing profile too (for calories).
        # tier is derived from the profile alone, so it is reported even with no check-in yet --
        # a brand-new athlete should still see which tier they are in and what the next one adds.
        return jsonify(profile=profile, readiness=None, calories=None, ai_status="skipped",
                       tier=derive_tier(profile),
                       needs_checkin=True, needs_profile=profile is None), 200

    # Recent history unlocks the AI's trend-aware recommendations (a 3x Rest streak -> "schedule a
    # recovery day", declining sleep, rising fatigue, a sharp load spike). The engine reads only
    # entry.metrics + entry.assessment, so we forward exactly those two fields per entry: a small,
    # JSON-safe payload that's insulated from the rest of the stored entry shape. Bounded to the most
    # recent window so the request stays well under the ai container's body limit. Fewer than three
    # entries simply yields no trend items (the engine no-ops), so a new athlete is unaffected.
    trend_history = [
        {"metrics": e.get("metrics"), "assessment": e.get("assessment")}
        for e in entries[-_HISTORY_WINDOW:] if isinstance(e, dict)
    ]

    # profile may be None -> build_features scores on the metrics alone. It also translates the
    # profile's training_program into features["performed"] for the balance analysis (#566).
    prediction = ai_client.predict(
        current_app.config["AI_URL"],
        ai_client.build_features(profile, metrics, history=trend_history),
        timeout=current_app.config["AI_CLIENT_TIMEOUT"],
    )
    if not isinstance(prediction, dict):
        # ai unreachable (None) or a malformed non-object response -> degrade gracefully, never crash
        return jsonify(profile=profile, readiness=None, calories=None, plan=None,
                       tier=derive_tier(profile),          # profile-only, so it survives an ai outage
                       ai_status="unavailable", needs_profile=profile is None), 200

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
    # PROPOSAL-v2 §3's Beginner output (#528 item 1), relayed under the same finite-number guard as
    # calories and coerced to a whole session count -- a fractional or out-of-range value from ai is
    # not a week anyone can train, so it is dropped rather than rendered.
    frequency = prediction.get("recommended_frequency")
    recommended_frequency = int(frequency) if _finite_number(frequency) and 1 <= frequency <= 7 else None
    # The timestamp of the entry this score came from. Readiness is scored from the LATEST check-in, which
    # is only *today's* when the athlete checked in today — so the card can name the day it actually scored
    # instead of always claiming "today's check-in" (#450). Reporting it from here ties the label to the
    # scored entry itself; deriving it client-side from a separate /history read could drift.
    scored_at = latest.get("timestamp") if isinstance(latest, dict) else None
    return jsonify(profile=profile, readiness=readiness,
                   calories=calories if _finite_number(calories) else None,
                   recommended_frequency=recommended_frequency,
                   tier=derive_tier(profile),
                   # F5's workout plan, relayed as-is once validated (#410). The card is rendered client-side;
                   # the dashboard is only the courier, so the shape stays the ai container's contract.
                   plan=_workout_plan(prediction.get("plan")),
                   scored_at=scored_at if isinstance(scored_at, str) else None,
                   ai_status="ok", needs_profile=profile is None), 200
