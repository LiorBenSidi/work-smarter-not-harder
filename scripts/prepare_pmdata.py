#!/usr/bin/env python3
"""Collect only wellness.csv and srpe.csv from PMData participants p01..p16."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

PARTICIPANTS = tuple(f"p{i:02d}" for i in range(1, 17))
REQUIRED_FILES = ("wellness.csv", "srpe.csv")


def find_file(participant_dir: Path, filename: str) -> Path | None:
    matches = [path for path in participant_dir.rglob(filename) if path.is_file()]
    if not matches:
        return None
    matches.sort(key=lambda path: (len(path.parts), str(path).lower()))
    return matches[0]


def collect_pmdata(source_root: Path, output_root: Path) -> int:
    source_root = source_root.resolve()
    output_root = output_root.resolve()

    if not source_root.is_dir():
        print(f"[ERROR] Source directory does not exist: {source_root}")
        return 1

    output_root.mkdir(parents=True, exist_ok=True)

    copied = 0
    missing: list[str] = []

    for participant in PARTICIPANTS:
        participant_dir = source_root / participant
        if not participant_dir.is_dir():
            print(f"[MISSING] Participant directory: {participant_dir}")
            missing.append(f"{participant}: participant directory")
            continue

        participant_output = output_root / participant
        participant_output.mkdir(parents=True, exist_ok=True)
        print(f"\n[{participant}]")

        for filename in REQUIRED_FILES:
            source_file = find_file(participant_dir, filename)
            if source_file is None:
                print(f"  [MISSING] {filename}")
                missing.append(f"{participant}: {filename}")
                continue

            destination = participant_output / filename
            shutil.copy2(source_file, destination)
            copied += 1
            print(f"  [COPIED] {source_file} -> {destination}")

    expected = len(PARTICIPANTS) * len(REQUIRED_FILES)
    print("\n" + "=" * 60)
    print(f"Copied {copied} of {expected} files.")
    print(f"Output directory: {output_root}")

    if missing:
        print("\nMissing items:")
        for item in missing:
            print(f"  - {item}")
        return 2

    print("All required PMData files were collected successfully.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect wellness.csv and srpe.csv for p01..p16."
    )
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(collect_pmdata(args.source, args.output))


if __name__ == "__main__":
    main()