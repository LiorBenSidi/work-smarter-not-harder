"""The model seam — the single function the job queue works in parallel.

OWNER of the *body*: Shiri (the Random Forest + recommendation engine).
OWNER of the *signature*: Elad (the queue calls it from a worker process).

`predict_one` is deliberately a module-level function: `ProcessPoolExecutor` pickles it by
qualified name, so it must stay importable as `inference.predict_one` and must not close over
app/request state. Load the baked model once at import time (module scope) so each worker process
pays for it exactly once, not per request.

CONTRACT (the `web -> ai` response shape — see docs/DESIGN.md):
    predict_one({...features...}) -> {"state": str, "proba": {str: float}, "recommendations": [...]}
"""

import logging
from pathlib import Path
import joblib
import numpy as np
import pandas as pd


logger = logging.getLogger(__name__)


# Load the trained model bundle once when this module is imported.
# Each worker process therefore pays the loading cost only once.
_MODEL_PATH = Path(__file__).resolve().parent / "model" / "model.pkl"
_MODEL_BUNDLE = joblib.load(_MODEL_PATH)

_PIPELINE = _MODEL_BUNDLE["pipeline"]
_FEATURE_ORDER = list(_MODEL_BUNDLE["feature_order"])
_CLASS_LABELS = list(_MODEL_BUNDLE["class_labels"])
_READY_THRESHOLD = float(_MODEL_BUNDLE["ready_threshold"])


def _safe_float(value):
    """Convert a feature value to float; missing or invalid values become NaN."""
    if value is None:
        return np.nan

    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return np.nan

    if not np.isfinite(numeric_value):
        return np.nan

    return numeric_value


def _web_wellness_to_model_scale(value):
    """Map the web's 1-10 wellness scale to the model's 1-5 scale."""
    numeric_value = _safe_float(value)

    if np.isnan(numeric_value):
        return np.nan

    if not 1.0 <= numeric_value <= 10.0:
        return np.nan

    return 1.0 + (numeric_value - 1.0) * 4.0 / 9.0


def _build_feature_vector(features):
    """Build one model input row in the exact feature order used during training."""
    if not isinstance(features, dict):
        features = {}

    values = {}

    for name in _FEATURE_ORDER:
        raw_value = features.get(name)

        if name in {"fatigue", "soreness"}:
            value = _web_wellness_to_model_scale(raw_value)
        else:
            value = _safe_float(raw_value)

        values[name] = [value]

    return pd.DataFrame(values, columns=_FEATURE_ORDER)


def _choose_state(probabilities):
    """Choose the readiness state while enforcing the trained Ready threshold."""
    probability_by_class = {
        label: float(probability)
        for label, probability in zip(_CLASS_LABELS, probabilities)
    }

    ready_probability = probability_by_class.get("Ready", 0.0)

    if (
        ready_probability >= _READY_THRESHOLD
        and ready_probability == max(probability_by_class.values())
    ):
        return "Ready"

    non_ready_labels = [
        label for label in _CLASS_LABELS
        if label != "Ready"
    ]

    return max(
        non_ready_labels,
        key=lambda label: probability_by_class[label],
    )



def predict_one(features):
    """Score one feature vector. Pure, CPU-bound, no I/O — safe to run in a worker process."""
    logger.info(
        "predict called with %d feature(s)",
        len(features) if isinstance(features, dict) else 0,
    )

    feature_vector = _build_feature_vector(features)

    probabilities = _PIPELINE.predict_proba(feature_vector)[0]

    probability_by_class = {
        label: float(probability)
        for label, probability in zip(_CLASS_LABELS, probabilities)
    }

    state = _choose_state(probabilities)

    return {
        "state": state,
        "proba": probability_by_class,
        "recommendations": [],
    }