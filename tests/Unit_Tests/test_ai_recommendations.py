import math

from ai.recommendations import calculate_calories, generate_recommendations


def test_recovery_recommendation_from_current_checkin():
    result = generate_recommendations(
        "Rest",
        {
            "sleep_hours": 4,
            "fatigue": 9,
            "soreness": 8,
            "training_load": 9,
            "goal": "maintain",
        },
    )

    assert result
    assert len(result) <= 5
    assert "sleep" in result[0].lower() or "fatigue" in result[0].lower()


def test_partial_input_still_returns_only_state_recommendation():
    result = generate_recommendations("Moderate", {})

    assert result == [
        "Readiness is moderate; use a controlled session and adjust if symptoms worsen."
    ]

    joined = " ".join(result).lower()
    assert "sleep was below" not in joined
    assert "fatigue is elevated" not in joined
    assert "soreness is elevated" not in joined
    assert "training load is elevated" not in joined


def test_history_trend_is_used_only_when_present():
    history = [
        {
            "assessment": "Moderate",
            "metrics": {
                "sleep_hours": 8,
                "fatigue": 4,
                "training_load": 3,
            },
        },
        {
            "assessment": "Rest",
            "metrics": {
                "sleep_hours": 7,
                "fatigue": 6,
                "training_load": 5,
            },
        },
        {
            "assessment": "Rest",
            "metrics": {
                "sleep_hours": 6,
                "fatigue": 8,
                "training_load": 8,
            },
        },
        {
            "assessment": "Rest",
            "metrics": {
                "sleep_hours": 5,
                "fatigue": 9,
                "training_load": 9,
            },
        },
    ]

    result = generate_recommendations("Rest", {"history": history})

    assert any("three check-ins" in item for item in result)
    assert any("Sleep has declined" in item for item in result)


def test_program_balance_supports_weekly_sets_mapping():
    result = generate_recommendations(
        "Ready",
        {
            "program": {
                "weekly_sets": {
                    "chest": 18,
                    "back": 8,
                    "legs": 4,
                }
            }
        },
    )

    assert any("Pressing volume" in item for item in result)
    assert any("legs" in item.lower() for item in result)


def test_calories_support_web_profile_field_names():
    calories = calculate_calories(
        {
            "age": 25,
            "gender": "female",
            "height": 165,
            "weight": 60,
            "goal": "maintain",
            "training_frequency": 4,
        }
    )

    assert isinstance(calories, int)
    assert calories >= 1200
    assert math.isfinite(calories)


def test_calories_support_model_style_profile_field_names():
    calories = calculate_calories(
        {
            "age": 25,
            "sex": "male",
            "height_cm": 175,
            "weight_kg": 70,
            "goal": "gain",
            "activity_level": "active",
        }
    )

    assert isinstance(calories, int)
    assert calories >= 1200
    assert math.isfinite(calories)


def test_missing_profile_skips_calories():
    assert calculate_calories({}) is None


def test_zero_or_negative_values_skip_calories():
    invalid_profiles = [
        {
            "age": 25,
            "gender": "female",
            "height": 165,
            "weight": 0,
            "goal": "maintain",
            "training_frequency": 4,
        },
        {
            "age": 25,
            "gender": "female",
            "height": -165,
            "weight": 60,
            "goal": "maintain",
            "training_frequency": 4,
        },
        {
            "age": 0,
            "gender": "female",
            "height": 165,
            "weight": 60,
            "goal": "maintain",
            "training_frequency": 4,
        },
    ]

    for profile in invalid_profiles:
        assert calculate_calories(profile) is None


def test_non_numeric_values_skip_calories():
    invalid_profiles = [
        {
            "age": "twenty",
            "gender": "female",
            "height": 165,
            "weight": 60,
            "goal": "maintain",
            "training_frequency": 4,
        },
        {
            "age": 25,
            "gender": "female",
            "height": None,
            "weight": 60,
            "goal": "maintain",
            "training_frequency": 4,
        },
        {
            "age": 25,
            "gender": "female",
            "height": 165,
            "weight": True,
            "goal": "maintain",
            "training_frequency": 4,
        },
    ]

    for profile in invalid_profiles:
        assert calculate_calories(profile) is None


def test_nan_and_infinity_skip_calories():
    invalid_profiles = [
        {
            "age": float("nan"),
            "gender": "female",
            "height": 165,
            "weight": 60,
            "goal": "maintain",
            "training_frequency": 4,
        },
        {
            "age": 25,
            "gender": "female",
            "height": float("inf"),
            "weight": 60,
            "goal": "maintain",
            "training_frequency": 4,
        },
        {
            "age": 25,
            "gender": "female",
            "height": 165,
            "weight": float("-inf"),
            "goal": "maintain",
            "training_frequency": 4,
        },
    ]

    for profile in invalid_profiles:
        assert calculate_calories(profile) is None


def test_unknown_goal_skips_calories():
    assert calculate_calories(
        {
            "age": 25,
            "gender": "female",
            "height": 165,
            "weight": 60,
            "goal": "bulk",
            "training_frequency": 4,
        }
    ) is None


def test_unknown_activity_level_skips_calories():
    assert calculate_calories(
        {
            "age": 25,
            "gender": "female",
            "height": 165,
            "weight": 60,
            "goal": "maintain",
            "activity_level": "extreme",
        }
    ) is None


def test_invalid_training_frequency_does_not_crash():
    calories = calculate_calories(
        {
            "age": 25,
            "gender": "female",
            "height": 165,
            "weight": 60,
            "goal": "maintain",
            "training_frequency": "four",
        }
    )

    assert isinstance(calories, int)
    assert calories >= 1200


def test_invalid_optional_history_and_program_are_ignored():
    result = generate_recommendations(
        "Ready",
        {
            "history": "not-a-list",
            "program": "not-a-program",
        },
    )

    assert result == [
        "Readiness is high; continue with the planned session using normal progression."
    ]