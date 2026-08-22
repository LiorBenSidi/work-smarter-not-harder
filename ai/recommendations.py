"""Deterministic recommendation engine for readiness, recovery, calories and optional trends.

The engine is intentionally pure and side-effect free so it can run safely inside the AI
process pool and be unit-tested on any machine.

Supported inputs:
- Current check-in: sleep_hours, fatigue, soreness, training_load
- Profile: age, gender, height, weight, goal, training_frequency
- Optional history: list of previous entries with metrics/assessment
- Optional performed: list/dict describing actual logged muscle-group training volume

Missing optional data is skipped; the engine never invents history or performed-volume details.

`performed` (not `program`) feeds the muscle-group balance analysis. `generate_workout_days`'s
prescribed plan is balanced by construction -- every split/frequency/equipment combination it
produces already lands inside the balance thresholds below, so an analysis fed prescribed volume
can never actually fire. Real signal needs what the athlete actually did, not what was assigned.
"""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

try:
    from calories import daily_calorie_target
except ImportError:
    from ai.calories import daily_calorie_target


def _finite_number(value: Any) -> float | None:
    """Return a finite float, otherwise None."""
    if isinstance(value, bool):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _activity_from_frequency(training_frequency: Any) -> str:
    """Map weekly training frequency to the activity labels used by calories.py."""
    frequency = _finite_number(training_frequency)
    if frequency is None:
        return "moderate"
    if frequency <= 1:
        return "sedentary"
    if frequency <= 3:
        return "light"
    if frequency <= 5:
        return "moderate"
    if frequency <= 7:
        return "active"
    return "very_active"


def calculate_calories(features: Any) -> int | None:
    """Return a calorie target for a complete valid profile, else None.

    Web profile names are translated to calories.py names:
    weight -> weight_kg, height -> height_cm, gender -> sex.
    """
    if not isinstance(features, dict):
        return None

    weight = _finite_number(
        features.get("weight", features.get("weight_kg"))
    )
    height = _finite_number(
        features.get("height", features.get("height_cm"))
    )
    age = _finite_number(features.get("age"))

    # Reject missing, non-finite, zero, and negative body measurements
    # before calories.py can attempt to round an infinite result.
    if (
        weight is None
        or height is None
        or age is None
        or weight <= 0
        or height <= 0
        or age <= 0
    ):
        return None

    gender = features.get("gender", features.get("sex"))
    activity = features.get("activity_level")
    if activity is None:
        activity = _activity_from_frequency(
            features.get("training_frequency")
        )

    try:
        calories = daily_calorie_target(
            weight,
            height,
            age,
            gender,
            activity,
            features.get("goal", "maintain"),
        )
    except (KeyError, TypeError, ValueError, OverflowError):
        return None

    numeric = _finite_number(calories)
    return int(round(numeric)) if numeric is not None else None


def _current_recovery_recommendations(state: str, features: dict[str, Any]) -> list[tuple[int, str]]:
    """Return prioritized recommendations from today's check-in."""
    sleep = _finite_number(features.get("sleep_hours"))
    fatigue = _finite_number(features.get("fatigue"))
    soreness = _finite_number(features.get("soreness"))
    load = _finite_number(features.get("training_load"))

    items: list[tuple[int, str]] = []

    if sleep is not None:
        if sleep < 5:
            items.append((100, "Prioritize recovery and additional sleep before a demanding session."))
        elif sleep < 7:
            items.append((82, "Sleep was below target; keep today's effort controlled."))

    if fatigue is not None:
        if fatigue >= 9:
            items.append((98, "Fatigue is very high; choose recovery or a substantially lighter session."))
        elif fatigue >= 7:
            items.append((80, "Fatigue is elevated; reduce intensity or training volume today."))

    if soreness is not None:
        if soreness >= 9:
            items.append((97, "Soreness is very high; avoid heavily loading the affected muscles today."))
        elif soreness >= 7:
            items.append((79, "Soreness is elevated; favor mobility, technique work, or unaffected muscle groups."))

    if load is not None:
        if load >= 9:
            items.append((92, "Recent training load is very high; avoid another maximal-load session."))
        elif load >= 7:
            items.append((74, "Training load is elevated; keep progression conservative and monitor recovery."))

    state_message = {
        "Rest": (70, "Recovery is the priority today; use rest or a light recovery session."),
        "Moderate": (55, "Readiness is moderate; use a controlled session and adjust if symptoms worsen."),
        "Ready": (35, "Readiness is high; continue with the planned session using normal progression."),
    }.get(state, (30, "Use a conservative session and reassess how you feel during training."))
    items.append(state_message)

    goal = str(features.get("goal", "")).strip().lower()
    if goal == "gain":
        calories = calculate_calories(features)
        if calories is not None:
            items.append((
                28,
                f"For a gain goal, eat more: target roughly {calories} kcal/day to support training and recovery.",
            ))
        else:
            items.append((
                28,
                "For a gain goal, eat more and prioritize consistent training quality to support growth.",
            ))
    elif goal == "lose":
        items.append((28, "For a loss goal, keep the calorie deficit moderate and preserve strength work."))
    elif goal == "maintain":
        items.append((28, "For maintenance, keep training and calorie intake consistent."))

    return items


def _history_recommendations(history: Any) -> list[tuple[int, str]]:
    """Analyze optional recent history without assuming it exists."""
    if not isinstance(history, list) or len(history) < 3:
        return []

    recent = history[-5:]
    states = [entry.get("assessment") for entry in recent if isinstance(entry, dict)]

    items: list[tuple[int, str]] = []
    if len(states) >= 3 and states[-3:] == ["Rest", "Rest", "Rest"]:
        items.append((96, "Readiness has remained low across three check-ins; schedule a recovery-focused day."))

    sleep_values = []
    fatigue_values = []
    load_values = []
    for entry in recent:
        if not isinstance(entry, dict):
            continue
        metrics = entry.get("metrics")
        if not isinstance(metrics, dict):
            continue
        for key, target in (
            ("sleep_hours", sleep_values),
            ("fatigue", fatigue_values),
            ("training_load", load_values),
        ):
            value = _finite_number(metrics.get(key))
            if value is not None:
                target.append(value)

    if len(sleep_values) >= 3 and all(
        later < earlier for earlier, later in zip(sleep_values[-3:], sleep_values[-2:])
    ):
        items.append((88, "Sleep has declined across recent check-ins; reduce load until recovery stabilizes."))

    if len(fatigue_values) >= 3 and all(
        later > earlier for earlier, later in zip(fatigue_values[-3:], fatigue_values[-2:])
    ):
        items.append((87, "Fatigue has risen across recent check-ins; plan a lower-load session."))

    if len(load_values) >= 3 and load_values[-1] > load_values[-3] * 1.5:
        items.append((84, "Training load increased sharply over recent check-ins; avoid another large increase."))

    return items


def _program_recommendations(performed: Any) -> list[tuple[float, str]]:
    """Analyze actual logged muscle-group weekly volume when present.

    Shape-agnostic (works on any volume distribution it's handed): the name predates this
    function being pointed at logged/performed data instead of a prescribed plan, kept to avoid
    unnecessary churn in its tests and call sites.

    Accepted forms:
    - {"weekly_sets": {"chest": 16, "back": 8, ...}}
    - [{"muscle_group": "chest", "sets": 4}, ...]
    """
    volumes: dict[str, float] = defaultdict(float)

    if isinstance(performed, dict):
        weekly_sets = performed.get("weekly_sets")
        if isinstance(weekly_sets, dict):
            for muscle, sets in weekly_sets.items():
                value = _finite_number(sets)
                if value is not None and value >= 0:
                    volumes[str(muscle).strip().lower()] += value
    elif isinstance(performed, list):
        for item in performed:
            if not isinstance(item, dict):
                continue
            muscle = item.get("muscle_group")
            sets = _finite_number(item.get("sets"))
            if isinstance(muscle, str) and sets is not None and sets >= 0:
                volumes[muscle.strip().lower()] += sets

    if not volumes:
        return []

    items: list[tuple[float, str]] = []
    for muscle, sets in sorted(volumes.items()):
        if sets > 20:
            # Ties within the same priority band break by severity, not by which muscle group's
            # name happens to sort first alphabetically -- further past the threshold is
            # genuinely more urgent. Bounded to (0, 0.9): a tie-break addition can never reach
            # the next real score above this band (79) or collide with anything else in use.
            severity = min((sets - 20) / 40, 1.0) * 0.9
            items.append((76 + severity, f"Weekly {muscle} volume is high; consider reducing sets or spreading them across sessions."))
        elif sets < 6:
            # sets is already known >= 0 (the parsing loop above only ever admits non-negative
            # values) -- an EXCLUSIVE `0 < sets` here silently dropped a muscle logged at exactly
            # 0, the single clearest "low" case there is: tracked, and trained for nothing.
            severity = ((6 - sets) / 6) * 0.9
            items.append((58 + severity, f"Weekly {muscle} volume is low; consider adding gradual volume if it matches your goal."))

    chest = volumes.get("chest")
    back = volumes.get("back")
    # `is not None`, not truthiness: both are logged-volume numbers, and 0 is a real, meaningful
    # value here (the muscle was tracked and trained for zero sets) -- `if chest and back:` would
    # silently skip the single most extreme imbalance this check exists to catch (one side at 0
    # while the other is trained). Division by exactly 0 is handled explicitly rather than left to
    # raise, and 0:0 is not an imbalance (neither side is over- or under-worked relative to the
    # other) so it is deliberately not flagged.
    if chest is not None and back is not None and (chest or back):
        if back == 0:
            items.append((73, "Pressing volume is much higher than pulling volume; add back work or reduce chest volume."))
        elif chest == 0:
            items.append((73, "Pulling volume is much higher than pressing volume; review upper-body balance."))
        else:
            ratio = chest / back
            if ratio > 1.5:
                items.append((73, "Pressing volume is much higher than pulling volume; add back work or reduce chest volume."))
            elif ratio < 0.67:
                items.append((73, "Pulling volume is much higher than pressing volume; review upper-body balance."))

    return items


def generate_recommendations(state: str, features: Any, *, max_items: int = 5) -> list[str]:
    """Return a prioritized recommendation list.

    Current check-in recommendations always work. History/performed-volume analysis is added
    only when those optional structures are actually provided.
    """
    if not isinstance(features, dict):
        features = {}

    candidates = []
    candidates.extend(_current_recovery_recommendations(state, features))
    candidates.extend(_history_recommendations(features.get("history")))
    candidates.extend(_program_recommendations(features.get("performed")))

    ordered: list[str] = []
    seen: set[str] = set()
    for _, message in sorted(candidates, key=lambda item: item[0], reverse=True):
        if message in seen:
            continue
        ordered.append(message)
        seen.add(message)
        if len(ordered) >= max_items:
            break

    return ordered