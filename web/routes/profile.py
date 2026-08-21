"""Profile routes — GET/POST /profile (gated). OWNER: Lior (F2 route + the db side).

The current user's profile (docs/DESIGN.md §2: age, gender, height, weight, goal,
training_frequency), the two OPTIONAL training preferences F5 plans from — equipment and
split_preference — and the OPTIONAL training_program the Advanced tier provides (#566, weekly sets
per muscle group). Input is validated + injection-safe before any query; the profile store is
injected (``app.config["PROFILES"]`` — the web->db seam: ``.get`` / ``.save``).
"""
import logging
import math

from flask import Blueprint, current_app, jsonify, request, session

from routes.auth import login_required

logger = logging.getLogger(__name__)

profile_bp = Blueprint("profile", __name__)

GOALS = {"lose", "maintain", "gain"}

# F5 (the workout generator, #276) needs FOUR inputs: goal · available training days · equipment ·
# split preference. `goal` and `training_frequency` above already cover the first two; these are the
# missing half — until they exist, F5 has nothing to plan from (see #276's 29 Jul comment).
#
# Both are OPTIONAL and are OMITTED from the stored profile when the caller doesn't send them, so
# every profile saved before this shipped keeps exactly its old shape and no existing client is
# forced to change. An explicit empty `equipment` list is kept: "I have no equipment" is an answer,
# and it is not the same as "not asked yet".
EQUIPMENT = ("bodyweight", "dumbbell", "barbell", "kettlebell", "machine", "bands", "pullup_bar")
SPLITS = ("full_body", "upper_lower", "push_pull_legs", "no_preference")

# PROPOSAL-v2 §3's Advanced tier asks the athlete to *provide* their current programme, not only to
# receive one -- the half of §3 that was never built (#566, #528 item 2). This is that input, held as
# weekly sets per muscle group.
#
# Muscle-group level rather than per-exercise, per docs/PERFORMED_VOLUME_SPEC.md "Option 1": `web`
# then never needs `ai/exercise_catalog.py`'s exercise list or its muscle-group mapping, so the two
# containers stay as decoupled as they are today. The 10 groups are ai/'s own taxonomy -- matching it
# exactly is what makes every logged set actually count in the balance analysis.
TRAINING_PROGRAM_GROUPS = ("chest", "back", "shoulders", "biceps", "triceps",
                           "quads", "hamstrings", "glutes", "calves", "core")
MAX_SETS_PER_GROUP = 60          # one week, one muscle group -- well past any real programme


def _validate_training_program(value):
    """Return a clean ``{muscle_group: weekly_sets}`` dict, or ``None`` when the caller supplied none.

    A group set to **0 is stored**, not dropped (#583). This used to read a 0 as "I don't train it"
    and discard it, which quietly destroyed the single most extreme case the balance analysis exists
    to catch: `chest: 12, back: 0` is the largest pressing:pulling imbalance possible, and it never
    reached `ai` at all. "I don't train it" now has its own unambiguous expression -- leave the box
    blank, which the form says in as many words and which never reaches this function -- so 0 is free
    to mean the number zero.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        # catches an injection object's siblings (a list, a bare string) before any of it is stored
        raise ValueError("training_program must be an object")
    if len(value) > len(TRAINING_PROGRAM_GROUPS):
        raise ValueError(f"training_program may list at most {len(TRAINING_PROGRAM_GROUPS)} muscle groups")
    clean = {}
    for group, sets in value.items():
        if not isinstance(group, str) or group not in TRAINING_PROGRAM_GROUPS:
            raise ValueError(f"training_program keys must each be one of {sorted(TRAINING_PROGRAM_GROUPS)}")
        # bool is an int subclass, so exclude it explicitly -- as the numeric profile fields do
        if isinstance(sets, bool) or not isinstance(sets, int):
            raise ValueError(f"training_program['{group}'] must be an integer")
        if not 0 <= sets <= MAX_SETS_PER_GROUP:
            raise ValueError(f"training_program['{group}'] must be 0-{MAX_SETS_PER_GROUP}")
        clean[group] = sets          # 0 included -- see the docstring (#583)
    return clean


def _validate_equipment(value):
    """Return a clean equipment list, or ``None`` when the caller supplied none."""
    if value is None:
        return None
    if not isinstance(value, list):
        # catches an injection object AND a bare string — a string is not a list, so it never
        # reaches the loop below, where it would otherwise be iterated one character at a time
        raise ValueError("equipment must be a list")
    if len(value) > len(EQUIPMENT):
        raise ValueError(f"equipment may list at most {len(EQUIPMENT)} items")
    clean = []
    for item in value:
        # no separate bool guard is needed here (unlike the numeric fields): True is not a `str`
        if not isinstance(item, str) or item not in EQUIPMENT:
            raise ValueError(f"equipment items must each be one of {sorted(EQUIPMENT)}")
        if item not in clean:                    # de-duplicate, keeping the caller's order
            clean.append(item)
    return clean


def _validate_split(value):
    """Return a clean split preference, or ``None`` when the caller supplied none."""
    if value is None:
        return None
    if not isinstance(value, str) or value not in SPLITS:   # True is not a `str`, so no bool guard
        raise ValueError(f"split_preference must be one of {sorted(SPLITS)}")
    return value


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
        if not math.isfinite(value):                 # explicit: reject NaN/Infinity (don't rely on the range bound alone)
            raise ValueError(f"{name} must be a finite number")
        if not lo <= value <= hi:
            raise ValueError(f"{name} must be {lo}-{hi}")
        return value

    gender = data.get("gender")
    if not isinstance(gender, str) or not 1 <= len(gender.strip()) <= 32:
        raise ValueError("gender must be a short string")
    goal = data.get("goal")
    if not isinstance(goal, str) or goal not in GOALS:
        raise ValueError(f"goal must be one of {sorted(GOALS)}")

    equipment = _validate_equipment(data.get("equipment"))
    split_preference = _validate_split(data.get("split_preference"))
    training_program = _validate_training_program(data.get("training_program"))

    clean = {
        "age": _num("age", 10, 120, integer=True),
        "gender": gender.strip(),
        "height": _num("height", 50, 300, integer=False),
        "weight": _num("weight", 20, 500, integer=False),
        "goal": goal,
        "training_frequency": _num("training_frequency", 0, 14, integer=True),
    }
    # Added only when supplied — a payload without them stores exactly the six fields it always did.
    if equipment is not None:
        clean["equipment"] = equipment
    if split_preference is not None:
        clean["split_preference"] = split_preference
    if training_program is not None:
        clean["training_program"] = training_program
    return clean


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
