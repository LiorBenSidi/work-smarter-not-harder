"""Split-day mapping (F5) -- resolves a training split from goal-independent inputs.

Pure, deterministic, no I/O -- same style as ai/calories.py and ai/recommendations.py. This is the
first stage of the workout generator: it decides WHICH split doctrine governs the week (full body /
upper-lower / push-pull-legs). Turning a resolved split + day count into actual day-by-day exercise
selections is separate, later work that consumes this module's output.
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


def resolve_split_preference(split_preference: Any, training_frequency: Any) -> str | list[str]:
    """Resolve a split preference into one concrete split, or a list of options to prompt on.

    An explicit split_preference (one of the three concrete splits) passes through unchanged --
    the athlete already chose, so there is nothing to resolve. "no_preference", or anything
    unrecognized (the safest fallback for bad/injected input -- never crash the engine), is
    resolved from training_frequency using the profile's real 0-7-day training week:

    - <=3 days/week -> "full_body" (single, unambiguous choice)
    - 4  days/week  -> ["full_body", "upper_lower"]      -- ask the athlete, don't guess
    - 5  days/week  -> ["upper_lower", "push_pull_legs"] -- ask the athlete, don't guess
    - >=6 days/week -> "push_pull_legs" (single; 6-7 is the realistic max in a 7-day week, but
      the profile allows training_frequency up to 14 -- treated the same as 6-7 rather than
      raising, matching the engine's "degrade, don't crash" rule)

    An unparseable/missing training_frequency defaults to "full_body" -- the least presumptuous
    choice when the day count itself is unknown.
    """
    if split_preference in _RESOLVED_SPLITS:
        return split_preference

    frequency = _safe_training_frequency(training_frequency)
    if frequency is None or frequency <= 3:
        return "full_body"
    if frequency == 4:
        return ["full_body", "upper_lower"]
    if frequency == 5:
        return ["upper_lower", "push_pull_legs"]
    return "push_pull_legs"
