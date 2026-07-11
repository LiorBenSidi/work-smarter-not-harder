"""Unit tests for the real AI inference implementation.

These tests verify Shiri's Random Forest inference path independently of the
job queue and HTTP layer.
"""

import json
import math
import pickle

import pytest


VALID_STATES = {"Rest", "Moderate", "Ready"}

FULL_FEATURES = {
    "sleep_hours": 8,
    "fatigue": 2,
    "soreness": 1,
    "training_load": 100,
}


def test_predict_one_returns_required_contract(inference_module):
    """A valid prediction must preserve the web-to-AI response contract."""
    result = inference_module.predict_one(FULL_FEATURES)

    assert isinstance(result, dict)
    assert {"state", "proba", "recommendations"}.issubset(result.keys())
    assert isinstance(result["state"], str)
    assert isinstance(result["proba"], dict)
    assert isinstance(result["recommendations"], list)


def test_predict_one_returns_valid_readiness_state(inference_module):
    """The predicted state must be one of the three trained readiness classes."""
    result = inference_module.predict_one(FULL_FEATURES)

    assert result["state"] in VALID_STATES


def test_probabilities_are_valid_and_sum_to_one(inference_module):
    """Every class probability must be finite, bounded, and sum to one."""
    result = inference_module.predict_one(FULL_FEATURES)
    probabilities = result["proba"]

    assert set(probabilities.keys()) == VALID_STATES

    for probability in probabilities.values():
        assert isinstance(probability, float)
        assert math.isfinite(probability)
        assert 0.0 <= probability <= 1.0

    assert sum(probabilities.values()) == pytest.approx(1.0)


def test_partial_input_does_not_crash(inference_module):
    """Missing model features are handled by the fitted median imputer."""
    result = inference_module.predict_one(
        {
            "sleep_hours": 7,
            "fatigue": 3,
        }
    )

    assert result["state"] in VALID_STATES
    assert set(result["proba"].keys()) == VALID_STATES


def test_all_model_features_missing_does_not_crash(inference_module):
    """Input without any trained model feature must degrade safely."""
    result = inference_module.predict_one({"hrv": 60})

    assert result["state"] in VALID_STATES
    assert set(result["proba"].keys()) == VALID_STATES


def test_extra_features_are_ignored(inference_module):
    """Features not used by the model must not change its prediction."""
    baseline = inference_module.predict_one(FULL_FEATURES)

    features_with_extra_values = {
        **FULL_FEATURES,
        "hrv": 60,
        "resting_hr": 55,
        "unknown_feature": 999,
    }

    result = inference_module.predict_one(features_with_extra_values)

    assert result == baseline


@pytest.mark.parametrize(
    "invalid_value",
    [
        None,
        "not-a-number",
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_invalid_feature_values_are_handled_safely(
    inference_module,
    invalid_value,
):
    """Invalid numeric values are treated as missing."""
    features = {
        **FULL_FEATURES,
        "fatigue": invalid_value,
    }

    result = inference_module.predict_one(features)

    assert result["state"] in VALID_STATES
    assert set(result["proba"].keys()) == VALID_STATES


def test_feature_dictionary_order_does_not_change_prediction(inference_module):
    """Prediction must follow trained feature order, not dict insertion order."""
    normal_order = {
        "sleep_hours": 8,
        "fatigue": 2,
        "soreness": 1,
        "training_load": 100,
    }

    different_order = {
        "training_load": 100,
        "soreness": 1,
        "fatigue": 2,
        "sleep_hours": 8,
    }

    assert (
        inference_module.predict_one(normal_order)
        == inference_module.predict_one(different_order)
    )


def test_non_dictionary_input_degrades_safely(inference_module):
    """Unexpected input types are treated as missing input."""
    result = inference_module.predict_one(None)

    assert result["state"] in VALID_STATES
    assert set(result["proba"].keys()) == VALID_STATES


def test_result_is_pickle_and_json_serializable(inference_module):
    """The process pool and HTTP API must serialize the result."""
    result = inference_module.predict_one(FULL_FEATURES)

    pickle.dumps(result)
    json.dumps(result)


def test_ready_threshold_is_enforced(inference_module, monkeypatch):
    """Ready must not be selected below the configured threshold."""
    monkeypatch.setattr(inference_module, "_READY_THRESHOLD", 0.70)

    probabilities = [
        0.10,  # Rest
        0.25,  # Moderate
        0.65,  # Ready
    ]

    state = inference_module._choose_state(probabilities)

    assert state == "Moderate"


def test_ready_is_selected_when_it_reaches_threshold(
    inference_module,
    monkeypatch,
):
    """Ready may be selected when it is highest and reaches the threshold."""
    monkeypatch.setattr(inference_module, "_READY_THRESHOLD", 0.58)

    probabilities = [
        0.10,  # Rest
        0.25,  # Moderate
        0.65,  # Ready
    ]

    state = inference_module._choose_state(probabilities)

    assert state == "Ready"