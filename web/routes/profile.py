"""Profile routes — GET/POST /profile (gated). OWNER: Lior (F2 route; Elad owns the db side).

The current user's profile (docs/DESIGN.md §2: age, gender, height, weight, goal,
training_frequency). Input is validated + injection-safe before any query; the profile store is
injected (``app.config["PROFILES"]`` — the web->db seam: ``.get`` / ``.save``).
"""
import logging

from flask import Blueprint, current_app, jsonify, request, session

from routes.auth import login_required

logger = logging.getLogger(__name__)

profile_bp = Blueprint("profile", __name__)

GOALS = {"lose", "maintain", "gain"}


def validate_profile(data):
    """Return a clean profile dict for a well-formed payload, else raise ``ValueError``.

    Every field is type- and range-checked; non-primitive values (e.g. a ``{"$gt": ""}`` injection
    object) are rejected before any query. ``bool`` is explicitly excluded from the numeric fields
    (it is an ``int`` subclass in Python).
    """
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")

    def _num(name, lo, hi, *, integer):
        value = data.get(name)
        allowed = int if integer else (int, float)  # bool excluded below (it is an int subclass)
        if isinstance(value, bool) or not isinstance(value, allowed):
            raise ValueError(f"{name} must be {'an integer' if integer else 'a number'}")
        if not lo <= value <= hi:
            raise ValueError(f"{name} must be {lo}-{hi}")
        return value

    gender = data.get("gender")
    if not isinstance(gender, str) or not 1 <= len(gender.strip()) <= 32:
        raise ValueError("gender must be a short string")
    goal = data.get("goal")
    if not isinstance(goal, str) or goal not in GOALS:
        raise ValueError(f"goal must be one of {sorted(GOALS)}")

    return {
        "age": _num("age", 10, 120, integer=True),
        "gender": gender.strip(),
        "height": _num("height", 50, 300, integer=False),
        "weight": _num("weight", 20, 500, integer=False),
        "goal": goal,
        "training_frequency": _num("training_frequency", 0, 14, integer=True),
    }


def _profiles():
    return current_app.config["PROFILES"]


@profile_bp.get("/profile")
@login_required
def get_profile():
    try:
        profile = _profiles().get(session["username"])
    except Exception:
        logger.exception("profile store unavailable during get")
        return jsonify(error="profile store unavailable"), 503
    return jsonify(profile=profile), 200


@profile_bp.post("/profile")
@login_required
def save_profile():
    try:
        clean = validate_profile(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    try:
        _profiles().save(session["username"], clean)
    except Exception:
        logger.exception("profile store unavailable during save")
        return jsonify(error="profile store unavailable"), 503
    return jsonify(status="saved", profile=clean), 200
