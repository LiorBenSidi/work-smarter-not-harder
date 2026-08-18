"""Workout plan generation (F5) -- turns a resolved split into actual days/exercises.

Pure, deterministic, no I/O -- same style as ai/calories.py and ai/recommendations.py. Three
stages: resolve_split_preference decides WHICH split doctrine governs the week (full body /
upper-lower / push-pull-legs); day_focus_sequence turns that into an ordered list of day-by-day
focuses; generate_workout_days fills each day with exercises drawn from EXERCISE_CATALOG.

Output shape agreed with Lior on #410: resolve_split_preference returns a fragment of the
`/predict` `plan` field -- either a resolved `{"split", "days"}` or an unresolved
`{"split_options"}` for the dashboard to render as a picker. generate_workout_days fills in
`days` once a resolved split is available.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

try:
    from exercise_catalog import EXERCISE_CATALOG
except ImportError:
    from ai.exercise_catalog import EXERCISE_CATALOG

# Must match web/routes/profile.py's SPLITS tuple exactly (the two containers don't share imports,
# so this is a duplicated contract by convention -- same pattern as exercise_catalog.py's EQUIPMENT).
SPLITS = ("full_body", "upper_lower", "push_pull_legs", "no_preference")

_RESOLVED_SPLITS = ("full_body", "upper_lower", "push_pull_legs")


def _safe_training_frequency(value: Any) -> int | None:
    """Coerce to a non-negative int, or None if unusable. Mirrors the engine's tolerant parsing."""
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric) or numeric < 0:
        return None
    return int(round(numeric))


def resolve_split_preference(split_preference: Any, training_frequency: Any) -> dict[str, Any]:
    """Resolve a split preference into a fragment of the `/predict` `plan` contract (#410).

    Returns {"split": <str>, "days": None} when the split is unambiguous, or
    {"split_options": [...]} when the athlete must be asked to choose -- the dashboard renders a
    picker for the latter (agreed with Lior on #410). `days` is a placeholder: it stays None until
    exercise selection, the next stage of the generator, is built.

    An explicit split_preference (one of the three concrete splits) passes through unchanged --
    the athlete already chose, so there is nothing to resolve. "no_preference", or anything
    unrecognized (the safest fallback for bad/injected input -- never crash the engine), is
    resolved from training_frequency using the profile's real 0-7-day training week:

    - <=3 days/week -> {"split": "full_body", "days": None} (single, unambiguous choice)
    - 4  days/week  -> {"split_options": ["full_body", "upper_lower"]}      -- ask, don't guess
    - 5  days/week  -> {"split_options": ["upper_lower", "push_pull_legs"]} -- ask, don't guess
    - >=6 days/week -> {"split": "push_pull_legs", "days": None} (6-7 is the realistic max in a
      7-day week, but the profile allows training_frequency up to 14 -- treated the same as 6-7
      rather than raising, matching the engine's "degrade, don't crash" rule)

    An unparseable/missing training_frequency defaults to {"split": "full_body", "days": None} --
    the least presumptuous choice when the day count itself is unknown.
    """
    if split_preference in _RESOLVED_SPLITS:
        return {"split": split_preference, "days": None}

    frequency = _safe_training_frequency(training_frequency)
    if frequency is None or frequency <= 3:
        return {"split": "full_body", "days": None}
    if frequency == 4:
        return {"split_options": ["full_body", "upper_lower"]}
    if frequency == 5:
        return {"split_options": ["upper_lower", "push_pull_legs"]}
    return {"split": "push_pull_legs", "days": None}


# The minimum day count a split needs to complete one full cycle. Below this, an explicit
# split_preference can reach here paired with a training_frequency resolve_split_preference never
# validated against it (it passes an explicit choice through unchanged, at any frequency) -- e.g.
# split_preference="push_pull_legs" with training_frequency=1 gives a week that is only ever
# "Push", never "Legs". full_body has no entry: every day is the same focus, so it can't truncate
# mid-cycle.
MIN_DAYS_FOR_SPLIT = {"push_pull_legs": 3, "upper_lower": 2}

_DAY_FOCUS_CYCLES = {
    "full_body": ("Full Body",),
    "upper_lower": ("Upper", "Lower"),
    "push_pull_legs": ("Push", "Pull", "Legs"),
}


def day_focus_sequence(split: str, training_frequency: Any) -> list[str]:
    """Turn a resolved split into an ordered list of day-focus labels, one per training day.

    This does NOT change what resolve_split_preference returned -- plan["split"] stays exactly
    what it resolved to. It only decides, locally, which focus cycle to walk when building the
    day-by-day sequence: if day_count is too low for `split` to complete one full cycle, this
    function walks the full_body cycle instead for that sequence only.

    day_count = min(safe_training_frequency, 7), floored at 0 for an unusable/unparseable
    training_frequency (0 days, an empty sequence -- never a guessed count, matching the
    engine's "never invent, degrade gracefully" rule elsewhere in ai/).
    """
    frequency = _safe_training_frequency(training_frequency)
    day_count = 0 if frequency is None else min(frequency, 7)

    minimum = MIN_DAYS_FOR_SPLIT.get(split)
    effective_split = "full_body" if minimum is not None and day_count < minimum else split

    cycle = _DAY_FOCUS_CYCLES.get(effective_split, _DAY_FOCUS_CYCLES["full_body"])
    return [cycle[day % len(cycle)] for day in range(day_count)]


# --- exercise selection --------------------------------------------------------------------
# Turns a day_focus_sequence into actual exercises. Goal shapes sets/reps only, never which
# exercises get picked (mirrors the rest of the engine: goal is a volume/intensity lever, not
# a selection lever).

GOAL_SETS_REPS = {
    "gain": (4, "6-8"),
    "maintain": (3, "8-12"),
    "lose": (3, "12-15"),
}

# For entries where exercise_catalog.py marks is_isometric=True (e.g. Plank) -- a rep range
# doesn't mean anything for a held position, so these get a duration instead. Set counts match
# GOAL_SETS_REPS for consistency; duration mirrors the same low<->high direction reps already
# use: gain sits at GOAL_SETS_REPS's lowest-volume/highest-effort end, so it gets the shortest
# hold, lose (highest-volume/endurance end) gets the longest, maintain in between.
GOAL_ISOMETRIC_SETS_DURATION = {
    "gain": (4, "20-30s"),
    "maintain": (3, "30-45s"),
    "lose": (3, "45-60s"),
}

# Derived from the catalog, not hardcoded: any glutes-group entry whose name says adductor or
# abductor. Excluded from the generic glutes pick so the two slots (general glutes vs.
# adductor/abductor) never select the same exercise twice.
_ADDUCTOR_ABDUCTOR_NAMES = frozenset(
    entry["name"]
    for entry in EXERCISE_CATALOG
    if entry["muscle_group"] == "glutes"
    and ("adductor" in entry["name"].lower() or "abductor" in entry["name"].lower())
)

_UPPER_TARGETS = (
    ("chest", "push"),
    ("shoulders", None),
    ("back", "pull"),
    ("biceps", "pull"),
    ("triceps", "push"),
    ("core", "core"),
)

_PUSH_PULL_TARGETS = {
    "Push": (("chest", "push"), ("shoulders", "push"), ("triceps", "push"), ("core", "core")),
    "Pull": (("back", "pull"), ("biceps", "pull"), ("shoulders", "pull")),
}


def _athlete_equipment(equipment: Any) -> set[str]:
    """Normalize to a set of strings. None/missing/garbage -> empty set (bodyweight-only,
    per #410: an empty/absent list is "no equipment", not "unknown")."""
    if not isinstance(equipment, list):
        return set()
    return {item for item in equipment if isinstance(item, str)}


def _select_exercise(
    muscle_group: str,
    pattern: str | None,
    available_equipment: set[str],
    *,
    exclude: set[str] = frozenset(),
    prefer_compound: bool = True,
    allow_fallback: bool = True,
) -> dict | None:
    """Pick one catalog entry for a muscle_group, or None if nothing is eligible.

    Eligible = matching muscle_group (+ pattern, if given), not already picked this day
    (`exclude`), and either bodyweight or in the athlete's equipment. Prefers `prefer_compound`
    (compound by default; isolation when a slot explicitly wants it).

    allow_fallback controls what happens when nothing of the preferred kind is eligible:
    - True (default): fall back to the other kind rather than returning nothing -- this is the
      per-muscle-group PRIMARY pick's job, where some coverage beats no coverage.
    - False: return None instead. For a slot with a hard type requirement -- e.g. Full Body's
      supplementary "Leg Extension" quads slot, which exists specifically to add isolation work
      on top of the primary compound quads pick. Falling back to another compound there would
      just duplicate the primary slot's role under a different label, so it skips instead
      (same "never invent, gracefully skip" rule already used for the no-machine
      adductor/abductor gap and the bodyweight-only Pull gaps).

    Ties break on catalog declaration order -- deterministic, no randomness.
    """
    candidates = [
        entry
        for entry in EXERCISE_CATALOG
        if entry["muscle_group"] == muscle_group
        and (pattern is None or entry["pattern"] == pattern)
        and entry["name"] not in exclude
        and (entry["equipment"] in available_equipment or entry["equipment"] == "bodyweight")
    ]
    if not candidates:
        return None

    preferred = [entry for entry in candidates if entry["is_compound"] == prefer_compound]
    if not allow_fallback:
        return preferred[0] if preferred else None

    fallback = [entry for entry in candidates if entry["is_compound"] != prefer_compound]
    return (preferred + fallback)[0]


def _select_adductor_abductor(
    available_equipment: set[str], *, exclude: set[str] = frozenset()
) -> dict | None:
    """The dedicated hip adductor/abductor slot (Lower/Legs only) -- both catalog entries are
    machine-only and non-compound, so this never applies the compound-first preference; it just
    finds the first eligible one, or None if the athlete has no machine equipment."""
    candidates = [
        entry
        for entry in EXERCISE_CATALOG
        if entry["name"] in _ADDUCTOR_ABDUCTOR_NAMES
        and entry["name"] not in exclude
        and (entry["equipment"] in available_equipment or entry["equipment"] == "bodyweight")
    ]
    return candidates[0] if candidates else None


def _to_plan_exercise(entry: dict, goal_key: str) -> dict:
    """goal_key must already be a valid GOAL_SETS_REPS/GOAL_ISOMETRIC_SETS_DURATION key
    (normalized once by the caller) -- picks the duration table instead of the rep-range table
    when the catalog marks this entry is_isometric=True."""
    table = GOAL_ISOMETRIC_SETS_DURATION if entry["is_isometric"] else GOAL_SETS_REPS
    sets, reps = table[goal_key]
    return {
        "name": entry["name"],
        "sets": sets,
        "reps": reps,
        "muscle_group": entry["muscle_group"],
    }


def _pick(
    picks: list[dict],
    exclude: set[str],
    muscle_group: str,
    pattern: str | None,
    equipment: set[str],
    *,
    prefer_compound: bool = True,
    allow_fallback: bool = True,
) -> None:
    """Select one exercise and append it (mutating picks/exclude) if something matched."""
    entry = _select_exercise(
        muscle_group,
        pattern,
        equipment,
        exclude=exclude,
        prefer_compound=prefer_compound,
        allow_fallback=allow_fallback,
    )
    if entry is not None:
        exclude.add(entry["name"])
        picks.append(entry)


def _full_body_exercises(equipment: set[str]) -> list[dict]:
    """Legs are compressed to 4 slots rather than one-per-sub-group: a compound squat (quads
    primary, glutes secondary -- covers glutes via overlap, no separate glutes-general or
    adductor/abductor slot here), a *supplementary* isolation quads exercise, an isolation
    hamstrings exercise, and a calf raise. Everything else is one exercise per listed muscle
    group.

    The supplementary quads slot (Leg Extension) does NOT fall back to another compound quads
    exercise when no isolation option is equipment-eligible -- the primary Squat slot already
    covers quads, so a fallback there would just duplicate it under a different label. It skips
    instead (allow_fallback=False), same principle as the no-machine adductor/abductor gap.
    The Leg Curl slot is hamstrings' ONLY slot in Full Body, so it keeps the normal fallback --
    some hamstrings coverage beats none.
    """
    picks: list[dict] = []
    exclude: set[str] = set()

    _pick(picks, exclude, "quads", "legs", equipment, prefer_compound=True)   # Squat
    _pick(  # Leg Extension -- supplementary, skip rather than duplicate the Squat slot
        picks, exclude, "quads", "legs", equipment,
        prefer_compound=False, allow_fallback=False,
    )
    _pick(picks, exclude, "hamstrings", "legs", equipment, prefer_compound=False)  # Leg Curl
    _pick(picks, exclude, "calves", "legs", equipment)                        # Calf Raise
    _pick(picks, exclude, "chest", "push", equipment)
    _pick(picks, exclude, "shoulders", None, equipment)
    _pick(picks, exclude, "back", "pull", equipment)
    _pick(picks, exclude, "biceps", "pull", equipment)
    _pick(picks, exclude, "triceps", "push", equipment)
    _pick(picks, exclude, "core", "core", equipment)

    return picks


def _upper_exercises(equipment: set[str]) -> list[dict]:
    picks: list[dict] = []
    exclude: set[str] = set()
    for muscle_group, pattern in _UPPER_TARGETS:
        _pick(picks, exclude, muscle_group, pattern, equipment)
    return picks


def _leg_full_coverage_exercises(equipment: set[str]) -> list[dict]:
    """Lower and Legs both use this -- full leg coverage, up to 5 exercises: quads, hamstrings,
    general glutes (adductor/abductor names excluded so the two glutes slots can't collide),
    the dedicated adductor/abductor slot, and calves. No core."""
    picks: list[dict] = []
    exclude: set[str] = set()

    _pick(picks, exclude, "quads", "legs", equipment)
    _pick(picks, exclude, "hamstrings", "legs", equipment)

    general_glutes = _select_exercise(
        "glutes", "legs", equipment, exclude=exclude | _ADDUCTOR_ABDUCTOR_NAMES
    )
    if general_glutes is not None:
        exclude.add(general_glutes["name"])
        picks.append(general_glutes)

    adductor_abductor = _select_adductor_abductor(equipment, exclude=exclude)
    if adductor_abductor is not None:
        exclude.add(adductor_abductor["name"])
        picks.append(adductor_abductor)

    _pick(picks, exclude, "calves", "legs", equipment)

    return picks


def _push_pull_exercises(focus: str, equipment: set[str]) -> list[dict]:
    """Core is a fixed slot on Push only (not Pull) -- natural rest-day spacing across the PPL
    cycle, and frequency that scales with training_frequency instead of being capped at 1x/week
    the way a first-occurrence-only rule would be."""
    picks: list[dict] = []
    exclude: set[str] = set()

    for muscle_group, pattern in _PUSH_PULL_TARGETS[focus]:
        _pick(picks, exclude, muscle_group, pattern, equipment)

    return picks


def generate_workout_days(
    split: str, training_frequency: Any, equipment: Any, goal: Any
) -> list[dict]:
    """Turn a resolved split into the `plan["days"]` list of the `/predict` contract (#410).

    Only meaningful once resolve_split_preference has produced a resolved {"split": ...} --
    there is nothing to generate for the {"split_options": [...]} (ambiguous) case.
    """
    sequence = day_focus_sequence(split, training_frequency)
    athlete_equipment = _athlete_equipment(equipment)
    goal_key = goal if isinstance(goal, str) and goal in GOAL_SETS_REPS else "maintain"

    days = []
    for day_index, focus in enumerate(sequence):
        if focus == "Full Body":
            picks = _full_body_exercises(athlete_equipment)
        elif focus == "Upper":
            picks = _upper_exercises(athlete_equipment)
        elif focus in ("Lower", "Legs"):
            picks = _leg_full_coverage_exercises(athlete_equipment)
        elif focus in _PUSH_PULL_TARGETS:
            picks = _push_pull_exercises(focus, athlete_equipment)
        else:
            picks = []  # defensive: day_focus_sequence never actually emits anything else

        days.append(
            {
                "day": day_index + 1,
                "focus": focus,
                "exercises": [_to_plan_exercise(entry, goal_key) for entry in picks],
            }
        )

    return days


def flatten_plan_to_volume(days: Any) -> list[dict]:
    """Flatten a `plan["days"]` list into the flat muscle-group volume shape
    `ai/recommendations.py::_program_recommendations` accepts: `[{"muscle_group", "sets"}, ...]`,
    summed across every day and exercise in the plan.

    Not called anywhere in the live `/predict` path. `_program_recommendations` is fed
    `features["performed"]` (actual logged volume), not the prescribed plan this function
    flattens -- prescribed volume from `generate_workout_days` is balanced by construction
    (every day/split/equipment combination lands inside the analyser's own thresholds), so
    feeding it prescribed volume can never fire a real recommendation. This function exists as a
    reusable utility for anything that legitimately needs prescribed weekly volume (e.g. a future
    "prescribed vs. performed" comparison view), not as part of the recommendation trigger.

    Defensive on malformed input (never the live model's own output, but this is a public utility):
    a non-list `days`, or entries missing the expected keys, contribute nothing rather than raise.
    """
    if not isinstance(days, list):
        return []

    volumes: dict[str, float] = defaultdict(float)

    for day in days:
        if not isinstance(day, dict):
            continue
        exercises = day.get("exercises")
        if not isinstance(exercises, list):
            continue
        for exercise in exercises:
            if not isinstance(exercise, dict):
                continue
            muscle_group = exercise.get("muscle_group")
            sets = exercise.get("sets")
            if not isinstance(muscle_group, str):
                continue
            if not isinstance(sets, (int, float)) or isinstance(sets, bool):
                continue
            volumes[muscle_group] += sets

    return [
        {"muscle_group": muscle_group, "sets": sets}
        for muscle_group, sets in volumes.items()
    ]
