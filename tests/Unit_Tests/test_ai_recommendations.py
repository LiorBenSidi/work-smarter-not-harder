import math

from ai.recommendations import calculate_calories, calculate_recommended_frequency, generate_recommendations


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


def test_gain_goal_recommends_eating_more_with_a_calorie_target():
    profile = {
        "age": 25,
        "gender": "male",
        "height": 180,
        "weight": 75,
        "goal": "gain",
        "training_frequency": 4,
    }
    expected_calories = calculate_calories(profile)
    assert expected_calories is not None

    result = generate_recommendations(
        "Moderate",
        {
            "sleep_hours": 8,
            "fatigue": 2,
            "soreness": 1,
            "training_load": 3,
            **profile,
        },
    )

    joined = " ".join(result).lower()
    assert "eat more" in joined
    assert str(expected_calories) in " ".join(result)


def test_gain_goal_recommends_eating_more_without_a_profile():
    result = generate_recommendations("Moderate", {"goal": "gain"})

    joined = " ".join(result).lower()
    assert "eat more" in joined


def test_lose_and_maintain_goals_do_not_recommend_eating_more():
    for goal in ("lose", "maintain"):
        result = generate_recommendations("Moderate", {"goal": goal})
        joined = " ".join(result).lower()
        assert "eat more" not in joined


def test_performed_volume_supports_weekly_sets_mapping():
    result = generate_recommendations(
        "Ready",
        {
            "performed": {
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


def test_performed_volume_supports_flat_list_mapping_and_fires_on_realistic_imbalance():
    """The contract shape web/db is expected to send: a flat list of muscle-group/sets pairs
    aggregated over a trailing week, mirroring what an athlete who trained chest hard and never
    trained back would actually log -- not the generator's own balanced-by-construction output."""
    result = generate_recommendations(
        "Ready",
        {
            "performed": [
                {"muscle_group": "chest", "sets": 22},
                {"muscle_group": "shoulders", "sets": 12},
                {"muscle_group": "triceps", "sets": 10},
                {"muscle_group": "quads", "sets": 14},
                {"muscle_group": "back", "sets": 3},
            ]
        },
    )

    joined = " ".join(result).lower()
    assert "chest volume is high" in joined
    assert "back volume is low" in joined
    assert "pressing volume is much higher than pulling volume" in joined


def test_prescribed_program_alone_no_longer_fires_the_volume_recommendation():
    """Regression guard for the balanced-by-construction bug: a prescribed/program payload, with
    no performed data, must not trigger the muscle-group balance analysis anymore -- only
    features["performed"] does. Proves the fix, not just a rename."""
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

    assert result == [
        "Readiness is high; continue with the planned session using normal progression."
    ]


def test_a_muscle_group_logged_at_exactly_zero_sets_is_flagged_as_low():
    """Regression guard: `elif 0 < sets < 6` used to exclude exactly 0 from the low-volume band,
    so a muscle tracked and trained for nothing produced no message at all -- the same blind spot
    as never logging it. 0 is a real, meaningful value here, not an absence."""
    result = generate_recommendations(
        "Ready",
        {"performed": [{"muscle_group": "calves", "sets": 0}, {"muscle_group": "chest", "sets": 10}]},
    )
    assert any("calves volume is low" in item.lower() for item in result)


def test_chest_at_twelve_back_at_zero_fires_both_the_low_and_ratio_messages():
    """The exact live scenario this pair of fixes was written for: one side trained, the other at
    a real, logged zero -- the most extreme pressing:pulling imbalance possible. Both the
    per-muscle low-volume message and the ratio message must fire; neither silently skips zero."""
    result = generate_recommendations(
        "Ready",
        {"performed": [{"muscle_group": "chest", "sets": 12}, {"muscle_group": "back", "sets": 0},
                       {"muscle_group": "shoulders", "sets": 9}]},
    )
    joined = " ".join(result).lower()
    assert "back volume is low" in joined
    assert "pressing volume is much higher than pulling volume" in joined


def test_back_at_zero_fires_the_ratio_message_without_a_zero_division_crash():
    """`if chest and back:` used truthiness, so back == 0 (falsy) silently skipped the ratio
    check entirely -- exactly the case it exists to catch. Division by the literal 0 denominator
    must also not raise."""
    result = generate_recommendations(
        "Ready",
        {"performed": [{"muscle_group": "chest", "sets": 8}, {"muscle_group": "back", "sets": 0}]},
    )
    assert any("pressing volume is much higher than pulling volume" in item.lower() for item in result)


def test_chest_at_zero_fires_the_opposite_ratio_message():
    result = generate_recommendations(
        "Ready",
        {"performed": [{"muscle_group": "chest", "sets": 0}, {"muscle_group": "back", "sets": 8}]},
    )
    assert any("pulling volume is much higher than pressing volume" in item.lower() for item in result)


def test_chest_and_back_both_at_zero_does_not_fire_a_ratio_message():
    """0:0 is not an imbalance -- neither side is over- or under-worked relative to the other --
    so the ratio check must stay silent even though both individually read as low volume."""
    result = generate_recommendations(
        "Ready",
        {"performed": [{"muscle_group": "chest", "sets": 0}, {"muscle_group": "back", "sets": 0}]},
    )
    joined = " ".join(result).lower()
    assert "pressing volume" not in joined
    assert "pulling volume" not in joined


def test_low_volume_ties_break_by_severity_not_alphabetical_order():
    """Regression guard: back=4, calves=2 and core=3 all score the same base "low volume"
    priority, so the tie used to break on `sorted(volumes.items())`'s alphabetical order --
    an accident of muscle-group naming, not a judgement about which is more under-trained.
    calves (furthest from the 6-set boundary) must now rank first, core second, back last."""
    from ai.recommendations import _program_recommendations

    items = _program_recommendations([
        {"muscle_group": "back", "sets": 4},
        {"muscle_group": "calves", "sets": 2},
        {"muscle_group": "core", "sets": 3},
    ])
    ordered = [message for _, message in sorted(items, reverse=True)]
    assert ordered == [
        "Weekly calves volume is low; consider adding gradual volume if it matches your goal.",
        "Weekly core volume is low; consider adding gradual volume if it matches your goal.",
        "Weekly back volume is low; consider adding gradual volume if it matches your goal.",
    ]


def test_high_volume_ties_also_break_by_severity():
    """Same fix, the over-20 side: the muscle further past the cap is genuinely more urgent,
    so it must outrank one just barely over 20, regardless of alphabetical order."""
    from ai.recommendations import _program_recommendations

    items = _program_recommendations([
        {"muscle_group": "quads", "sets": 22},
        {"muscle_group": "chest", "sets": 40},
    ])
    ordered = [message for _, message in sorted(items, reverse=True)]
    assert ordered == [
        "Weekly chest volume is high; consider reducing sets or spreading them across sessions.",
        "Weekly quads volume is high; consider reducing sets or spreading them across sessions.",
    ]


def test_the_exact_reported_scenario_now_squeezes_out_back_not_core():
    """The full live-tested case: with the alphabetical tie-break, back and calves won the
    5-item cap and core was squeezed out -- an accident of "back" and "calves" sorting before
    "core". By severity, calves (furthest from the boundary) and core (next furthest) both
    outrank back (closest to the boundary, least severe), so back is squeezed out instead."""
    recs = generate_recommendations(
        "Rest",
        {
            "goal": "lose",
            "performed": [
                {"muscle_group": "chest", "sets": 25}, {"muscle_group": "back", "sets": 4},
                {"muscle_group": "shoulders", "sets": 9}, {"muscle_group": "biceps", "sets": 6},
                {"muscle_group": "triceps", "sets": 6}, {"muscle_group": "quads", "sets": 6},
                {"muscle_group": "hamstrings", "sets": 6}, {"muscle_group": "glutes", "sets": 6},
                {"muscle_group": "calves", "sets": 2}, {"muscle_group": "core", "sets": 3},
            ],
        },
    )
    joined = " ".join(recs).lower()
    assert "calves volume is low" in joined
    assert "core volume is low" in joined
    assert "back volume is low" not in joined  # squeezed out now, not core


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


def test_missing_profile_skips_recommended_frequency():
    assert calculate_recommended_frequency({}) is None


def test_zero_or_negative_values_skip_recommended_frequency():
    invalid_profiles = [
        {"age": 25, "height": 165, "weight": 0, "goal": "maintain"},
        {"age": 25, "height": -165, "weight": 60, "goal": "maintain"},
        {"age": 0, "height": 165, "weight": 60, "goal": "maintain"},
    ]

    for profile in invalid_profiles:
        assert calculate_recommended_frequency(profile) is None


def test_recommended_frequency_baseline_by_goal():
    """Under-50 profiles isolate the goal baseline from the age-50 adjustment: gain/lose favor
    more weekly sessions, maintain and an unrecognized/missing goal both fall back to 4."""
    base_profile = {"age": 30, "height": 165, "weight": 60}

    assert calculate_recommended_frequency({**base_profile, "goal": "gain"}) == 5
    assert calculate_recommended_frequency({**base_profile, "goal": "lose"}) == 5
    assert calculate_recommended_frequency({**base_profile, "goal": "maintain"}) == 4
    assert calculate_recommended_frequency({**base_profile, "goal": "bulk"}) == 4
    assert calculate_recommended_frequency(base_profile) == 4


def test_recommended_frequency_drops_by_one_at_age_fifty():
    """Regression guard for the exact boundary: 49 must be unaffected, 50 must be reduced by
    exactly one -- not two, not a different threshold."""
    profile = {"height": 165, "weight": 60, "goal": "gain"}

    assert calculate_recommended_frequency({**profile, "age": 49}) == 5
    assert calculate_recommended_frequency({**profile, "age": 50}) == 4


def test_recommended_frequency_stays_within_the_zero_to_seven_contract_range():
    """The field's contract is 0-7 sessions (docs/PROPOSAL.md §3 -- a real 7-day week). With
    today's goal/age formula the result only ever lands on 3-5 -- the clamp is a defensive no-op,
    not something these inputs actually exercise -- but the contract is what callers rely on, so
    it is asserted directly rather than assumed from the arithmetic."""
    for age in (1, 50, 120):
        for goal in ("gain", "lose", "maintain", "unknown"):
            result = calculate_recommended_frequency({"age": age, "height": 165, "weight": 60, "goal": goal})
            assert 0 <= result <= 7


def test_recommended_frequency_does_not_echo_the_profiles_training_frequency():
    """The one hard rule from the #528 contract: a recommendation that just returned the user's
    own training_frequency input would be indistinguishable from that input. The function never
    reads training_frequency at all, so this profile proves the two diverge in a real case."""
    profile = {"age": 30, "height": 165, "weight": 60, "goal": "maintain", "training_frequency": 6}

    result = calculate_recommended_frequency(profile)

    assert result == 4
    assert result != profile["training_frequency"]


def test_invalid_optional_history_and_performed_are_ignored():
    result = generate_recommendations(
        "Ready",
        {
            "history": "not-a-list",
            "performed": "not-performed-data",
        },
    )

    assert result == [
        "Readiness is high; continue with the planned session using normal progression."
    ]