"""Unit tests for readiness-score binning."""

import importlib.util
import math
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "build_training_dataset.py"


@pytest.fixture(scope="module")
def dataset_builder():
    """Load build_training_dataset.py as a module from its file path."""
    spec = importlib.util.spec_from_file_location(
        "build_training_dataset",
        SCRIPT_PATH,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, "Rest"),
        (4, "Rest"),
        (4.5, "Moderate"),
        (5, "Moderate"),
        (7, "Moderate"),
        (7.5, "Ready"),
        (8, "Ready"),
        (10, "Ready"),
    ],
)
def test_readiness_boundary_values_map_to_expected_class(
    dataset_builder,
    value,
    expected,
):
    """Boundary values must map to the intended readiness class."""
    assert dataset_builder.readiness_to_class(value) == expected


@pytest.mark.parametrize(
    "invalid_value",
    [
        -1,
        -0.1,
        10.1,
        -100,
        11,
        1000,
        float("nan"),
        None,
    ],
)
def test_invalid_readiness_values_return_none(
    dataset_builder,
    invalid_value,
):
    """Missing or out-of-range readiness values must not create a class."""
    assert dataset_builder.readiness_to_class(invalid_value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, "Rest"),
        (3.5, "Rest"),
        (6, "Moderate"),
        (6.5, "Moderate"),
        (9, "Ready"),
    ],
)
def test_values_inside_each_interval_map_correctly(
    dataset_builder,
    value,
    expected,
):
    """Representative values inside each interval must map correctly."""
    assert dataset_builder.readiness_to_class(value) == expected