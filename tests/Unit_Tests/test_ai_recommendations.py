import math

from ai.inference import _calculate_calories, _generate_recommendations


def test_rest_state_returns_recovery_recommendation():
    recommendations = _generate_recommendations(
        "Rest",
        {
            "sleep_hours": 8,
            "fatigue": 3,
            "soreness": 2,
            "training_load": 3,
        },
    )

    assert recommendations
    assert any("Recovery" in item for item in recommendations)


def test_concerning_metrics_are_prioritized():
    recommendations = _generate_recommendations(
        "Ready",
        {
            "sleep_hours": 4,
            "fatigue": 9,
            "soreness": 9,
            "training_load": 9,
        },
    )

    assert 1 <= len(recommendations) <= 4
    assert "sleep" in recommendations[0].lower() or "fatigue" in recommendations[0].lower()
    assert any("soreness" in item.lower() for item in recommendations)


def test_partial_input_still_returns_a_state_recommendation():
    recommendations = _generate_recommendations("Moderate", {})

    assert recommendations == [
        "Readiness is moderate; use a controlled session and adjust if symptoms worsen."
    ]


def test_valid_profile_returns_integer_calorie_target():
    calories = _calculate_calories(
        {
            "weight_kg": 70,
            "height_cm": 175,
            "age": 25,
            "sex": "female",
            "activity_level": "moderate",
            "goal": "maintain",
        }
    )

    assert isinstance(calories, int)
    assert calories >= 1200
    assert math.isfinite(calories)


def test_partial_or_invalid_profile_skips_calories():
    assert _calculate_calories({}) is None
    assert _calculate_calories(
        {
            "weight_kg": -1,
            "height_cm": 175,
            "age": 25,
            "sex": "female",
        }
    ) is None