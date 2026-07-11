#!/usr/bin/env python3
"""Tune class weights and a conservative Ready probability threshold.

The script keeps the selected feature set unchanged:
    sleep_hours, fatigue, soreness, training_load

It evaluates several class-weight policies with participant-grouped
cross-validation. Each fitted model is tested with several Ready thresholds.

A Ready threshold is conservative:
- the model may return Ready only when Ready is already the most probable class;
- if Ready is the top class but its probability is below the threshold,
  the prediction falls back to the more probable non-Ready class.

Selection rule:
1. Prefer candidates that satisfy minimum Ready precision and recall.
2. Among them, choose the highest mean participant-grouped Macro-F1.
3. Break ties with higher Ready precision and lower fold variability.

The final model bundle stores both the fitted pipeline and the selected
Ready threshold so inference.py can apply the same decision rule.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline

LOGGER = logging.getLogger(__name__)

FEATURE_ORDER = [
    "sleep_hours",
    "fatigue",
    "soreness",
    "training_load",
]

TARGET_COLUMN = "readiness_class"
GROUP_COLUMN = "participant"
CLASS_LABELS = ["Rest", "Moderate", "Ready"]

READINESS_BINNING = {
    "Rest": "0-4",
    "Moderate": "5-7",
    "Ready": "8-10",
}

# Keep the best tree structure found in the previous validation run.
RF_CONFIGURATIONS = [
    {
        "name": "leaf3_depth_none",
        "params": {
            "n_estimators": 500,
            "max_depth": None,
            "min_samples_leaf": 3,
            "max_features": "sqrt",
        },
    },
    {
        "name": "leaf4_depth_none",
        "params": {
            "n_estimators": 500,
            "max_depth": None,
            "min_samples_leaf": 4,
            "max_features": "sqrt",
        },
    },
    {
        "name": "leaf5_depth_none",
        "params": {
            "n_estimators": 500,
            "max_depth": None,
            "min_samples_leaf": 5,
            "max_features": "sqrt",
        },
    },
    {
        "name": "leaf6_depth_none",
        "params": {
            "n_estimators": 500,
            "max_depth": None,
            "min_samples_leaf": 6,
            "max_features": "sqrt",
        },
    },
    {
        "name": "leaf4_depth12",
        "params": {
            "n_estimators": 500,
            "max_depth": 12,
            "min_samples_leaf": 4,
            "max_features": "sqrt",
        },
    },
    {
        "name": "leaf4_depth16",
        "params": {
            "n_estimators": 500,
            "max_depth": 16,
            "min_samples_leaf": 4,
            "max_features": "sqrt",
        },
    },
]

READY_THRESHOLDS = [
    0.00,
    0.50,
    0.52,
    0.54,
    0.56,
    0.58,
    0.60,
    0.62,
    0.64,
    0.66,
    0.68,
    0.70,
]


@dataclass(frozen=True)
class CandidateResult:
    """Validation result for one class-weight and threshold combination."""

    name: str
    rf_name: str
    rf_params: dict[str, Any]
    class_weight: Any
    ready_threshold: float
    fold_macro_f1: list[float]
    mean_macro_f1: float
    std_macro_f1: float
    overall_macro_f1: float
    overall_accuracy: float
    ready_precision: float
    ready_recall: float
    ready_f1: float
    ready_predictions: int
    false_ready_predictions: int
    classification_report: dict[str, Any]
    confusion_matrix: list[list[int]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Tune Random Forest class weights and a conservative Ready threshold."
        )
    )
    parser.add_argument(
        "--dataset",
        required=True,
        type=Path,
        help="Path to pmdata_training_dataset_clean.csv.",
    )
    parser.add_argument(
        "--model-output",
        default=Path(__file__).resolve().parent / "model.pkl",
        type=Path,
        help="Where to save the tuned model bundle.",
    )
    parser.add_argument(
        "--report-output",
        default=Path(__file__).resolve().parent / "training_report.json",
        type=Path,
        help="Where to save the tuning report.",
    )
    parser.add_argument(
        "--folds",
        default=5,
        type=int,
        help="Number of participant-grouped validation folds.",
    )
    parser.add_argument(
        "--min-ready-precision",
        default=0.25,
        type=float,
        help=(
            "Minimum Ready precision required by the preferred-candidate pool. "
            "This is a model-selection rule, not a medical guarantee."
        ),
    )
    parser.add_argument(
        "--min-ready-recall",
        default=0.15,
        type=float,
        help=(
            "Minimum Ready recall required so the model does not avoid "
            "predicting Ready entirely."
        ),
    )
    return parser.parse_args()


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s: %(message)s",
    )


def load_and_validate_dataset(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(f"Dataset not found: {path}")

    df = pd.read_csv(path)

    required_columns = {
        *FEATURE_ORDER,
        TARGET_COLUMN,
        GROUP_COLUMN,
        "readiness",
        "date",
    }
    missing_columns = required_columns.difference(df.columns)
    if missing_columns:
        raise ValueError(
            f"Dataset is missing required columns: {sorted(missing_columns)}"
        )

    for column in FEATURE_ORDER + ["readiness"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    invalid_target = ~df[TARGET_COLUMN].isin(CLASS_LABELS)
    if invalid_target.any():
        invalid_values = sorted(
            df.loc[invalid_target, TARGET_COLUMN].astype(str).unique()
        )
        raise ValueError(f"Invalid readiness classes found: {invalid_values}")

    if df[GROUP_COLUMN].isna().any():
        raise ValueError("Participant values must not be missing.")

    duplicate_count = int(
        df.duplicated(subset=[GROUP_COLUMN, "date"]).sum()
    )
    if duplicate_count:
        raise ValueError(
            f"Found {duplicate_count} duplicate participant-date rows."
        )

    if (~df["readiness"].between(0, 10)).any():
        raise ValueError("Readiness values must be between 0 and 10.")

    if (df["training_load"] < 0).any():
        raise ValueError("training_load cannot be negative.")

    LOGGER.info(
        "Loaded %d rows from %d participants.",
        len(df),
        df[GROUP_COLUMN].nunique(),
    )
    LOGGER.info(
        "Class distribution: %s",
        df[TARGET_COLUMN].value_counts().to_dict(),
    )
    LOGGER.info(
        "Missing feature values: %s",
        df[FEATURE_ORDER].isna().sum().to_dict(),
    )

    return df.reset_index(drop=True)


def class_weight_options() -> list[tuple[str, Any]]:
    """Explainable weight policies to compare."""
    return [
        ("no_class_weight", None),
        ("balanced", "balanced"),
        (
            "ready_weight_1_25",
            {"Rest": 1.0, "Moderate": 1.0, "Ready": 1.25},
        ),
        (
            "ready_weight_1_50",
            {"Rest": 1.0, "Moderate": 1.0, "Ready": 1.50},
        ),
        (
            "ready_weight_2_00",
            {"Rest": 1.0, "Moderate": 1.0, "Ready": 2.00},
        ),
    ]


def build_pipeline(class_weight: Any, rf_params: dict[str, Any]) -> Pipeline:
    classifier = RandomForestClassifier(
        random_state=42,
        class_weight=class_weight,
        n_jobs=1,
        **rf_params,
    )

    return Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="median")),
            ("classifier", classifier),
        ]
    )


def predict_with_ready_threshold(
    pipeline: Pipeline,
    x: pd.DataFrame,
    ready_threshold: float,
) -> np.ndarray:
    """Apply a conservative threshold only when Ready is the top class."""
    probabilities = pipeline.predict_proba(x)
    classifier = pipeline.named_steps["classifier"]
    classes = np.asarray(classifier.classes_)

    ready_matches = np.where(classes == "Ready")[0]
    if len(ready_matches) != 1:
        raise RuntimeError(
            f"Expected one Ready class, found classes={classes.tolist()}"
        )

    ready_index = int(ready_matches[0])
    top_indices = np.argmax(probabilities, axis=1)
    predictions = classes[top_indices].astype(object)

    if ready_threshold <= 0:
        return predictions

    non_ready_indices = np.where(classes != "Ready")[0]

    for row_index, top_index in enumerate(top_indices):
        if top_index != ready_index:
            continue

        ready_probability = probabilities[row_index, ready_index]
        if ready_probability >= ready_threshold:
            continue

        fallback_local_index = int(
            np.argmax(probabilities[row_index, non_ready_indices])
        )
        fallback_class_index = int(non_ready_indices[fallback_local_index])
        predictions[row_index] = classes[fallback_class_index]

    return np.asarray(predictions, dtype=str)


def evaluate_weight_policy(
    df: pd.DataFrame,
    policy_name: str,
    class_weight: Any,
    rf_name: str,
    rf_params: dict[str, Any],
    folds: int,
) -> list[CandidateResult]:
    """Fit one model per fold, then test all thresholds without refitting."""
    x = df[FEATURE_ORDER]
    y = df[TARGET_COLUMN]
    groups = df[GROUP_COLUMN]

    unique_groups = groups.nunique()
    if folds < 2 or folds > unique_groups:
        raise ValueError(
            f"--folds must be between 2 and {unique_groups}; received {folds}."
        )

    splitter = GroupKFold(n_splits=folds)

    # Store fold predictions separately so each threshold gets fold metrics.
    fold_true: list[list[str]] = []
    fold_probabilities: list[np.ndarray] = []
    fold_classes: list[np.ndarray] = []

    LOGGER.info("Evaluating %s with class-weight policy: %s", rf_name, policy_name)

    for fold_number, (train_index, test_index) in enumerate(
        splitter.split(x, y, groups),
        start=1,
    ):
        train_groups = set(groups.iloc[train_index])
        test_groups = set(groups.iloc[test_index])

        overlap = train_groups.intersection(test_groups)
        if overlap:
            raise RuntimeError(
                f"Participant leakage in fold {fold_number}: {sorted(overlap)}"
            )

        pipeline = build_pipeline(class_weight, rf_params)
        pipeline.fit(x.iloc[train_index], y.iloc[train_index])

        probabilities = pipeline.predict_proba(x.iloc[test_index])
        classes = np.asarray(
            pipeline.named_steps["classifier"].classes_
        )

        fold_true.append(y.iloc[test_index].tolist())
        fold_probabilities.append(probabilities)
        fold_classes.append(classes)

        LOGGER.info(
            "%s fold %d: participants=%s, rows=%d",
            policy_name,
            fold_number,
            sorted(test_groups),
            len(test_index),
        )

    results: list[CandidateResult] = []

    for threshold in READY_THRESHOLDS:
        all_true: list[str] = []
        all_predicted: list[str] = []
        fold_scores: list[float] = []

        for true_values, probabilities, classes in zip(
            fold_true,
            fold_probabilities,
            fold_classes,
            strict=True,
        ):
            predictions = predictions_from_probabilities(
                probabilities=probabilities,
                classes=classes,
                ready_threshold=threshold,
            )

            fold_score = f1_score(
                true_values,
                predictions,
                labels=CLASS_LABELS,
                average="macro",
                zero_division=0,
            )
            fold_scores.append(float(fold_score))
            all_true.extend(true_values)
            all_predicted.extend(predictions.tolist())

        overall_macro_f1 = f1_score(
            all_true,
            all_predicted,
            labels=CLASS_LABELS,
            average="macro",
            zero_division=0,
        )
        overall_accuracy = accuracy_score(all_true, all_predicted)

        ready_precision = precision_score(
            all_true,
            all_predicted,
            labels=["Ready"],
            average="macro",
            zero_division=0,
        )
        ready_recall = recall_score(
            all_true,
            all_predicted,
            labels=["Ready"],
            average="macro",
            zero_division=0,
        )
        ready_f1 = f1_score(
            all_true,
            all_predicted,
            labels=["Ready"],
            average="macro",
            zero_division=0,
        )

        report = classification_report(
            all_true,
            all_predicted,
            labels=CLASS_LABELS,
            output_dict=True,
            zero_division=0,
        )
        matrix = confusion_matrix(
            all_true,
            all_predicted,
            labels=CLASS_LABELS,
        )

        ready_predictions = int(
            sum(prediction == "Ready" for prediction in all_predicted)
        )
        true_ready_predictions = int(
            sum(
                actual == "Ready" and predicted == "Ready"
                for actual, predicted in zip(
                    all_true,
                    all_predicted,
                    strict=True,
                )
            )
        )
        false_ready_predictions = ready_predictions - true_ready_predictions

        results.append(
            CandidateResult(
                name=f"{rf_name}__{policy_name}",
                rf_name=rf_name,
                rf_params=rf_params,
                class_weight=class_weight,
                ready_threshold=float(threshold),
                fold_macro_f1=fold_scores,
                mean_macro_f1=float(np.mean(fold_scores)),
                std_macro_f1=float(np.std(fold_scores)),
                overall_macro_f1=float(overall_macro_f1),
                overall_accuracy=float(overall_accuracy),
                ready_precision=float(ready_precision),
                ready_recall=float(ready_recall),
                ready_f1=float(ready_f1),
                ready_predictions=ready_predictions,
                false_ready_predictions=false_ready_predictions,
                classification_report=report,
                confusion_matrix=matrix.tolist(),
            )
        )

    return results


def predictions_from_probabilities(
    probabilities: np.ndarray,
    classes: np.ndarray,
    ready_threshold: float,
) -> np.ndarray:
    """Threshold helper used on stored cross-validation probabilities."""
    ready_matches = np.where(classes == "Ready")[0]
    if len(ready_matches) != 1:
        raise RuntimeError(
            f"Expected one Ready class, found classes={classes.tolist()}"
        )

    ready_index = int(ready_matches[0])
    top_indices = np.argmax(probabilities, axis=1)
    predictions = classes[top_indices].astype(object)

    if ready_threshold <= 0:
        return np.asarray(predictions, dtype=str)

    non_ready_indices = np.where(classes != "Ready")[0]

    for row_index, top_index in enumerate(top_indices):
        if top_index != ready_index:
            continue
        if probabilities[row_index, ready_index] >= ready_threshold:
            continue

        fallback_local_index = int(
            np.argmax(probabilities[row_index, non_ready_indices])
        )
        fallback_class_index = int(non_ready_indices[fallback_local_index])
        predictions[row_index] = classes[fallback_class_index]

    return np.asarray(predictions, dtype=str)


def select_best_candidate(
    results: list[CandidateResult],
    min_ready_precision: float,
    min_ready_recall: float,
) -> CandidateResult:
    """Select a useful, conservative candidate without suppressing Ready."""
    if not results:
        raise ValueError("No candidate results were produced.")

    eligible = [
        result
        for result in results
        if result.ready_precision >= min_ready_precision
        and result.ready_recall >= min_ready_recall
    ]

    if eligible:
        LOGGER.info(
            "%d candidates met Ready precision >= %.2f and recall >= %.2f.",
            len(eligible),
            min_ready_precision,
            min_ready_recall,
        )
        pool = eligible
    else:
        LOGGER.warning(
            "No candidate met both Ready constraints; "
            "falling back to the highest Ready precision, then Macro-F1."
        )
        return max(
            results,
            key=lambda result: (
                result.ready_precision,
                result.mean_macro_f1,
                result.ready_recall,
                -result.std_macro_f1,
            ),
        )

    return max(
        pool,
        key=lambda result: (
            result.mean_macro_f1,
            result.ready_precision,
            -result.std_macro_f1,
        ),
    )


def fit_final_model(
    df: pd.DataFrame,
    class_weight: Any,
    rf_params: dict[str, Any],
) -> Pipeline:
    pipeline = build_pipeline(class_weight, rf_params)
    pipeline.fit(df[FEATURE_ORDER], df[TARGET_COLUMN])
    return pipeline


def save_artifacts(
    model: Pipeline,
    best_result: CandidateResult,
    all_results: list[CandidateResult],
    df: pd.DataFrame,
    model_output: Path,
    report_output: Path,
    min_ready_precision: float,
    min_ready_recall: float,
) -> None:
    model_output = model_output.resolve()
    report_output = report_output.resolve()

    model_output.parent.mkdir(parents=True, exist_ok=True)
    report_output.parent.mkdir(parents=True, exist_ok=True)

    model_bundle = {
        "pipeline": model,
        "feature_order": FEATURE_ORDER,
        "class_labels": CLASS_LABELS,
        "readiness_binning": READINESS_BINNING,
        "ready_threshold": best_result.ready_threshold,
        "selected_candidate": best_result.name,
        "selected_class_weight": best_result.class_weight,
        "selected_params": best_result.rf_params,
        "validation_mean_macro_f1": best_result.mean_macro_f1,
        "validation_ready_precision": best_result.ready_precision,
        "validation_ready_recall": best_result.ready_recall,
        "training_rows": int(len(df)),
        "participant_count": int(df[GROUP_COLUMN].nunique()),
        "scikit_learn_version": sklearn.__version__,
    }

    joblib.dump(model_bundle, model_output)

    report = {
        "dataset": {
            "rows": int(len(df)),
            "participants": int(df[GROUP_COLUMN].nunique()),
            "class_distribution": {
                str(key): int(value)
                for key, value in df[TARGET_COLUMN].value_counts().items()
            },
            "features": FEATURE_ORDER,
            "target": TARGET_COLUMN,
            "readiness_binning": READINESS_BINNING,
        },
        "software": {
            "python": sys.version.split()[0],
            "scikit_learn": sklearn.__version__,
            "pandas": pd.__version__,
            "numpy": np.__version__,
            "joblib": joblib.__version__,
        },
        "model": {
            "random_forest_configurations": RF_CONFIGURATIONS,
            "ready_thresholds_tested": READY_THRESHOLDS,
            "minimum_ready_precision": min_ready_precision,
            "minimum_ready_recall": min_ready_recall,
        },
        "selection_rule": (
            "Among candidates meeting the Ready precision and recall floors, "
            "select the highest participant-grouped mean Macro-F1. "
            "Tie-breakers: higher Ready precision, then lower fold variance."
        ),
        "selected_candidate": asdict(best_result),
        "all_candidates": [asdict(result) for result in all_results],
    }

    report_output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    LOGGER.info("Saved tuned model bundle to: %s", model_output)
    LOGGER.info("Saved tuned training report to: %s", report_output)


def log_selected_candidate(result: CandidateResult) -> None:
    LOGGER.info("=" * 72)
    LOGGER.info("Selected candidate: %s", result.name)
    LOGGER.info("Random Forest configuration: %s", result.rf_name)
    LOGGER.info("Random Forest parameters: %s", result.rf_params)
    LOGGER.info("Class weight: %s", result.class_weight)
    LOGGER.info("Selected Ready threshold: %.2f", result.ready_threshold)
    LOGGER.info(
        "Mean fold Macro-F1: %.4f +/- %.4f",
        result.mean_macro_f1,
        result.std_macro_f1,
    )
    LOGGER.info("Overall Macro-F1: %.4f", result.overall_macro_f1)
    LOGGER.info("Overall Accuracy: %.4f", result.overall_accuracy)
    LOGGER.info(
        "Ready -> precision=%.4f recall=%.4f f1=%.4f predictions=%d false=%d",
        result.ready_precision,
        result.ready_recall,
        result.ready_f1,
        result.ready_predictions,
        result.false_ready_predictions,
    )
    LOGGER.info("Confusion matrix labels: %s", CLASS_LABELS)
    LOGGER.info("Confusion matrix: %s", result.confusion_matrix)

    for label in CLASS_LABELS:
        metrics = result.classification_report[label]
        LOGGER.info(
            "%s -> precision=%.4f recall=%.4f f1=%.4f support=%d",
            label,
            metrics["precision"],
            metrics["recall"],
            metrics["f1-score"],
            int(metrics["support"]),
        )


def main() -> None:
    configure_logging()
    args = parse_args()

    try:
        if not 0 <= args.min_ready_precision <= 1:
            raise ValueError("--min-ready-precision must be between 0 and 1.")
        if not 0 <= args.min_ready_recall <= 1:
            raise ValueError("--min-ready-recall must be between 0 and 1.")

        df = load_and_validate_dataset(args.dataset.resolve())

        results: list[CandidateResult] = []
        for rf_configuration in RF_CONFIGURATIONS:
            for policy_name, class_weight in class_weight_options():
                results.extend(
                    evaluate_weight_policy(
                        df=df,
                        policy_name=policy_name,
                        class_weight=class_weight,
                        rf_name=rf_configuration["name"],
                        rf_params=rf_configuration["params"],
                        folds=args.folds,
                    )
                )

        best_result = select_best_candidate(
            results=results,
            min_ready_precision=args.min_ready_precision,
            min_ready_recall=args.min_ready_recall,
        )
        log_selected_candidate(best_result)

        final_model = fit_final_model(
            df=df,
            class_weight=best_result.class_weight,
            rf_params=best_result.rf_params,
        )

        save_artifacts(
            model=final_model,
            best_result=best_result,
            all_results=results,
            df=df,
            model_output=args.model_output,
            report_output=args.report_output,
            min_ready_precision=args.min_ready_precision,
            min_ready_recall=args.min_ready_recall,
        )
    except Exception as error:
        LOGGER.exception("Tuning failed: %s", error)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()