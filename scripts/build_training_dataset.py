#!/usr/bin/env python3
"""Build the PMData training dataset for the final 4-feature model.

The script merges:
- wellness.csv
- srpe.csv

by participant and date.

Final model features:
- sleep_hours
- fatigue
- soreness
- training_load

Target:
- readiness_class

The raw PMData should remain outside the Git repository.
"""
# ruff: noqa: T201
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

PARTICIPANTS = tuple(f"p{i:02d}" for i in range(1, 17))

# Convert raw daily sRPE to the 0-10 scale used by the web check-in.
# The explored PMData training set had a 95th-percentile daily load of 596.
# Values at or above this reference are clipped to 10.
TRAINING_LOAD_REFERENCE = 596.0
TRAINING_LOAD_OUTPUT_MAX = 10.0

OUTPUT_COLUMNS = [
    "participant",
    "date",
    "sleep_hours",
    "fatigue",
    "soreness",
    "training_load",
    "readiness",
    "readiness_class",
]


def normalise_date(series: pd.Series) -> pd.Series:
    """Convert datetime-like values to timezone-free dates."""
    parsed = pd.to_datetime(series, errors="coerce", utc=True)
    return parsed.dt.tz_convert(None).dt.normalize()


def readiness_to_class(value: float) -> str | None:
    """Map readiness 0-10 into three classes."""
    if pd.isna(value) or value < 0 or value > 10:
        return None
    if value <= 4:
        return "Rest"
    if value <= 7:
        return "Moderate"
    return "Ready"


def normalize_training_load(value: float) -> float:
    """Map raw daily sRPE to the web contract's 0-10 load scale."""
    if pd.isna(value):
        return 0.0

    numeric_value = float(value)

    if numeric_value < 0:
        raise ValueError(
            f"training_load cannot be negative: {numeric_value}"
        )

    scaled_value = (
        numeric_value
        / TRAINING_LOAD_REFERENCE
        * TRAINING_LOAD_OUTPUT_MAX
    )

    return float(
        np.clip(
            scaled_value,
            0.0,
            TRAINING_LOAD_OUTPUT_MAX,
        )
    )


def load_wellness(path: Path, participant: str) -> pd.DataFrame:
    """Load and standardize one participant's wellness.csv."""
    df = pd.read_csv(path)

    required = {
        "effective_time_frame",
        "fatigue",
        "readiness",
        "sleep_duration_h",
        "soreness",
    }
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(
            f"{participant}: wellness.csv missing columns: {sorted(missing)}"
        )

    out = pd.DataFrame(
        {
            "participant": participant,
            "date": normalise_date(df["effective_time_frame"]),
            "sleep_hours": pd.to_numeric(
                df["sleep_duration_h"],
                errors="coerce",
            ),
            "fatigue": pd.to_numeric(
                df["fatigue"],
                errors="coerce",
            ),
            "soreness": pd.to_numeric(
                df["soreness"],
                errors="coerce",
            ),
            "readiness": pd.to_numeric(
                df["readiness"],
                errors="coerce",
            ),
        }
    )

    # Values of 0 are outside the valid 1-5 wellness scale.
    # Keep the rows and mark those measurements as missing.
    for column in ["fatigue", "soreness"]:
        out.loc[out[column] == 0, column] = np.nan

    # Zero sleep duration is treated as missing.
    out.loc[out["sleep_hours"] <= 0, "sleep_hours"] = np.nan

    out = out.dropna(subset=["date"])
    out = out.drop_duplicates(
        subset=["participant", "date"],
        keep="last",
    )

    return out


def load_srpe(path: Path, participant: str) -> pd.DataFrame:
    """Load sRPE sessions and aggregate daily training load."""
    df = pd.read_csv(path)

    required = {
        "end_date_time",
        "perceived_exertion",
        "duration_min",
    }
    missing = required.difference(df.columns)
    if missing:
        raise ValueError(
            f"{participant}: srpe.csv missing columns: {sorted(missing)}"
        )

    dates = normalise_date(df["end_date_time"])
    exertion = pd.to_numeric(
        df["perceived_exertion"],
        errors="coerce",
    )
    duration = pd.to_numeric(
        df["duration_min"],
        errors="coerce",
    )

    # NumPy vectorization: calculate all session loads at once.
    training_load = np.multiply(
        exertion.to_numpy(dtype=float),
        duration.to_numpy(dtype=float),
    )

    out = pd.DataFrame(
        {
            "date": dates,
            "training_load": training_load,
        }
    )

    out = out.dropna(subset=["date"])
    out["training_load"] = out["training_load"].fillna(0.0)

    return (
        out.groupby("date", as_index=False)["training_load"]
        .sum()
        .sort_values("date")
    )


def build_participant_dataset(
    participant_dir: Path,
    participant: str,
) -> pd.DataFrame:
    wellness_path = participant_dir / "wellness.csv"
    srpe_path = participant_dir / "srpe.csv"

    if not wellness_path.is_file():
        raise FileNotFoundError(
            f"{participant}: missing {wellness_path}"
        )
    if not srpe_path.is_file():
        raise FileNotFoundError(
            f"{participant}: missing {srpe_path}"
        )

    wellness = load_wellness(
        wellness_path,
        participant,
    )
    srpe = load_srpe(
        srpe_path,
        participant,
    )

    merged = wellness.merge(
        srpe,
        on="date",
        how="left",
    )

    # No matching sRPE record means no logged workout that day.
    merged["training_load"] = (
        merged["training_load"].fillna(0.0)
    )

    merged["readiness_class"] = (
        merged["readiness"].map(readiness_to_class)
    )

    return merged[OUTPUT_COLUMNS]


def build_dataset(source_root: Path) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []

    for participant in PARTICIPANTS:
        participant_dir = source_root / participant

        if not participant_dir.is_dir():
            print(
                f"[WARNING] Missing participant directory: "
                f"{participant_dir}"
            )
            continue

        frame = build_participant_dataset(
            participant_dir,
            participant,
        )
        frames.append(frame)

        missing_count = int(frame.isna().sum().sum())
        print(
            f"[OK] {participant}: "
            f"{len(frame)} daily rows, "
            f"{missing_count} missing values"
        )

    if not frames:
        raise RuntimeError("No participant data was loaded.")

    dataset = pd.concat(
        frames,
        ignore_index=True,
    )

    dataset = dataset.sort_values(
        ["participant", "date"],
        kind="stable",
    ).reset_index(drop=True)

    dataset["training_load"] = (
        dataset["training_load"]
        .map(normalize_training_load)
    )

    return dataset


def validate_ranges(dataset: pd.DataFrame) -> dict[str, int]:
    """Count suspicious or invalid values without silently deleting them."""
    return {
        "sleep_hours_below_0": int(
            (dataset["sleep_hours"] < 0).sum()
        ),
        "sleep_hours_above_24": int(
            (dataset["sleep_hours"] > 24).sum()
        ),
        "fatigue_outside_1_5": int(
            (
                dataset["fatigue"].notna()
                & ~dataset["fatigue"].between(1, 5)
            ).sum()
        ),
        "soreness_outside_1_5": int(
            (
                dataset["soreness"].notna()
                & ~dataset["soreness"].between(1, 5)
            ).sum()
        ),
        "training_load_below_0": int(
            (dataset["training_load"] < 0).sum()
        ),
        "training_load_above_10": int(
            (dataset["training_load"] > 10).sum()
        ),
        "readiness_outside_0_10": int(
            (
                dataset["readiness"].notna()
                & ~dataset["readiness"].between(0, 10)
            ).sum()
        ),
        "duplicate_participant_date": int(
            dataset.duplicated(
                subset=["participant", "date"]
            ).sum()
        ),
    }


def print_summary(dataset: pd.DataFrame) -> None:
    print("\n" + "=" * 72)
    print(f"Rows: {len(dataset)}")
    print(
        "Participants:",
        dataset["participant"].nunique(),
    )
    print(
        "Date range:",
        dataset["date"].min().date(),
        "to",
        dataset["date"].max().date(),
    )

    print("\nMissing values:")
    print(dataset.isna().sum().to_string())

    print("\nReadiness classes:")
    print(
        dataset["readiness_class"]
        .value_counts(dropna=False)
        .to_string()
    )

    print("\nFeature ranges:")
    feature_columns = [
        "sleep_hours",
        "fatigue",
        "soreness",
        "training_load",
        "readiness",
    ]
    print(
        dataset[feature_columns]
        .describe()
        .T
        .to_string()
    )

    print("\nData-quality checks:")
    checks = validate_ranges(dataset)
    for name, count in checks.items():
        print(f"{name}: {count}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge PMData wellness and sRPE files "
            "into the final 4-feature training dataset."
        )
    )
    parser.add_argument(
        "--source",
        required=True,
        type=Path,
        help=(
            "Path to reduced PMData folders "
            "containing p01..p16."
        ),
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path for the merged CSV.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = args.source.resolve()
    output = args.output.resolve()

    if not source.is_dir():
        print(
            f"[ERROR] Source directory does not exist: "
            f"{source}"
        )
        raise SystemExit(1)

    try:
        dataset = build_dataset(source)
    except Exception as error:
        print(
            f"[ERROR] {type(error).__name__}: "
            f"{error}"
        )
        raise SystemExit(2) from error

    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    dataset.to_csv(
        output,
        index=False,
        date_format="%Y-%m-%d",
    )

    print_summary(dataset)

    print(
        f"\nSaved training dataset to:\n"
        f"{output}"
    )


if __name__ == "__main__":
    main()