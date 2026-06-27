"""Calorie recommendation (F4) — Mifflin-St Jeor BMR -> TDEE -> goal-adjusted target.

Pure, dependency-free, deterministic (no model, no I/O), so it's trivially testable and runs on
any machine. OWNER: Lior (AI / recommendations). Wire it into the recommendation output (/predict)
or expose it however the AI container prefers — the contract is the two function signatures below.
"""

# Standard activity multipliers: TDEE = BMR * factor.
ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
    "very_active": 1.9,
}

# Goal -> daily kcal adjustment applied on top of maintenance (TDEE).
GOAL_ADJUSTMENTS = {
    "lose": -500,
    "maintain": 0,
    "gain": 500,
}

# Sex term in the Mifflin-St Jeor equation; an unmapped value uses the neutral midpoint
# (so the app never crashes on a profile that isn't strictly "male"/"female").
_SEX_OFFSETS = {"male": 5, "female": -161}
_NEUTRAL_SEX_OFFSET = (5 + -161) / 2  # -78.0

# Safety floor — never recommend a dangerously low intake.
MIN_SAFE_KCAL = 1200


def _positive_number(value, name):
    # bool is a subclass of int; reject it so True/False can't masquerade as 1/0.
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number, got {type(value).__name__}")
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {value}")
    return float(value)


def mifflin_st_jeor_bmr(weight_kg, height_cm, age, sex):
    """Basal metabolic rate (kcal/day), Mifflin-St Jeor.

    male: 10*kg + 6.25*cm - 5*age + 5 ; female: ... - 161 ; any other value: neutral midpoint.
    """
    weight_kg = _positive_number(weight_kg, "weight_kg")
    height_cm = _positive_number(height_cm, "height_cm")
    age = _positive_number(age, "age")
    offset = _SEX_OFFSETS.get(str(sex).strip().lower(), _NEUTRAL_SEX_OFFSET)
    return 10 * weight_kg + 6.25 * height_cm - 5 * age + offset


def daily_calorie_target(weight_kg, height_cm, age, sex, activity_level, goal):
    """Goal-adjusted daily calorie target (kcal, rounded to an int), floored at a safe minimum."""
    factor = ACTIVITY_FACTORS.get(str(activity_level).strip().lower())
    if factor is None:
        raise ValueError(f"unknown activity_level {activity_level!r}; expected one of {sorted(ACTIVITY_FACTORS)}")
    adjustment = GOAL_ADJUSTMENTS.get(str(goal).strip().lower())
    if adjustment is None:
        raise ValueError(f"unknown goal {goal!r}; expected one of {sorted(GOAL_ADJUSTMENTS)}")
    maintenance = mifflin_st_jeor_bmr(weight_kg, height_cm, age, sex) * factor
    return max(MIN_SAFE_KCAL, round(maintenance + adjustment))
