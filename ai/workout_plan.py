"""Split-day mapping (F5) -- resolves a training split from goal-independent inputs.

Pure, deterministic, no I/O -- same style as ai/calories.py and ai/recommendations.py. This is the
first stage of the workout generator: it decides WHICH split doctrine governs the week (full body /
upper-lower / push-pull-legs). Turning a resolved split + day count into actual day-by-day exercise
selections is separate, later work that consumes this module's output.

Output shape agreed with Lior on #410: `resolve_split_preference` returns a fragment of the
`/predict` `plan` field -- either a resolved `{"split", "days"}` or an unresolved
`{"split_options"}` for the dashboard to render as a picker.
"""

from __future__ import annotations

import math
from typing import Any

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
