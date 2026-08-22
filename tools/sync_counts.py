#!/usr/bin/env python3
"""Rewrite the suite-size numbers in the graded documents from a real collection.

Every count in `README.md`, `docs/REPORT.md` and `docs/SUBMISSION.md` used to be typed by hand,
restated about a dozen times. Two costs followed. Any test change silently invalidated all of them
until `tests/Integration_Tests/test_docs_contract.py` failed -- that guard *detects* drift but never
fixes it, so the repair was still a human measuring seven directories. And because every restatement
is a line two branches can both edit, parallel work collided on them repeatedly (#589 / #590 / #591
each hit it on the same day).

This tool is the other half of that guard: the guard says the numbers are wrong, this makes them
right. It measures exactly the way the guard measures, so the two can never disagree.

    python tools/sync_counts.py            # rewrite the numbers in place
    python tools/sync_counts.py --check    # exit 1 if any are stale, change nothing

**It only ever replaces digits.** Each site is matched by a regex anchored on the surrounding words,
and only that group's span is substituted -- never the sentence around it. The claim is testable
rather than asserted: corrupt any count, run this, and `git diff` comes back empty.

Pass/skip splits are NOT re-run (a full suite is ~110s, too slow for a hook). The skip count is read
from the document and the pass count recomputed as `total - skip`, which is precisely the invariant
the guard enforces -- it checks the split sums to the total, not that the run produced it.
"""
from __future__ import annotations

# A command-line tool: its report to the operator IS the product, and it must arrive on stdout even
# when logging is unconfigured. Same file-level exemption `scripts/prepare_pmdata.py` and
# `scripts/build_training_dataset.py` already use, for the same reason.
# ruff: noqa: T201

import argparse
import re
import subprocess  # nosec B404 - see _collect: a fixed argv, no shell, no external input
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TYPE_DIRS = {
    "Unit": "Unit_Tests", "Integration": "Integration_Tests", "Negative": "Negative_Tests",
    "System": "System_Tests", "Full-System": "Full_System_Tests", "Security": "Security_Tests",
    "Stress": "Stress_Tests",
}


# --------------------------------------------------------------------------- measurement
# Identical to test_docs_contract's: a separate process, so this is the real number and not the
# selection of whatever run happens to be in progress.

def _collect(target: str) -> int:
    # argv is a literal list (no shell), the executable is this interpreter, and `target` is never
    # user input: it is one of the seven directory names in TYPE_DIRS, or "tests/".
    proc = subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-m", "pytest", target, "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        sys.exit(f"collection failed for {target}:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    return sum(1 for line in proc.stdout.splitlines() if "::" in line)


def _test_functions() -> int:
    """Counted the way REPORT.md says it is counted -- `grep -c "^def test_"`, so unindented only."""
    return sum(
        1
        for path in (ROOT / "tests").rglob("*.py")
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.startswith("def test_")
    )


def measure() -> dict[str, int]:
    values = {"total": _collect("tests/"), "functions": _test_functions()}
    for label, directory in TYPE_DIRS.items():
        values[f"type:{label}"] = _collect(f"tests/{directory}")
    listed = sum(values[f"type:{label}"] for label in TYPE_DIRS)
    if listed != values["total"]:
        sys.exit(f"per-type counts sum to {listed} but the suite collects {values['total']} -- "
                 "a test directory exists that REPORT.md's totals line does not name")
    return values


# --------------------------------------------------------------------------- the sites
# (file, pattern, key, required). The pattern must name exactly one group `n`, and ONLY that group's
# span is replaced -- the surrounding sentence is copied through untouched. Anchored on surrounding
# words so a percentage, a year or an issue number can never match.
#
# `required=False` marks a site that legitimately may not exist: §4 gives a prose bullet to only some
# of the seven types, which `test_docs_contract` also tolerates ("not every type gets its own bullet").

SITES: list[tuple[str, str, str, bool]] = [
    ("docs/REPORT.md",     r"\*\*Suite at this snapshot:\*\* \*\*(?P<n>\d+) checks",                 "total",     True),
    ("docs/REPORT.md",     r"\*\*(?P<n>\d+) automated checks across the seven",                      "total",     True),
    ("docs/REPORT.md",     r"(?P<n>\d+) collected cases come from",                                  "total",     True),
    ("docs/REPORT.md",     r"The two supporting directories complete the (?P<n>\d+):",               "total",     True),
    ("README.md",          r"Suite: \*\*(?P<n>\d+) collected\*\*",                                   "total",     True),
    ("docs/SUBMISSION.md", r"`REPORT\.md`, (?P<n>\d+) tests",                                        "total",     True),
    ("docs/SUBMISSION.md", r"current — \*\*(?P<n>\d+) tests\*\*",                                    "total",     True),
    ("docs/REPORT.md",     r"come from \*\*(?P<n>\d+) test\nfunctions\*\*",                          "functions", True),
]

# Pass/skip pairs: (file, pattern with two groups -- pass then skip). Only the pass group is
# rewritten, to `total - skip`, preserving whatever skip the document states for that environment.
SPLIT_SITES: list[tuple[str, str]] = [
    ("docs/REPORT.md",     r"\*\*Suite at this snapshot:\*\* \*\*\d+ checks, (\d+) passing / (\d+) environment-gated\*\*"),
    ("docs/REPORT.md",     r"the current suite is \*\*(\d+) pass,\n(\d+) skip"),
    ("docs/REPORT.md",     r"suite is \*\*(\d+) pass, (\d+) skip\*\*"),
    ("docs/REPORT.md",     r"pytest -q {26}# (\d+) pass / (\d+) env-gated skip"),
    ("README.md",          r"Suite: \*\*\d+ collected\*\* \((\d+) pass / (\d+) environment-gated\)"),
    ("docs/SUBMISSION.md", r"\((\d+) pass / (\d+) env-gated in CI\)"),
]


def _type_sites() -> list[tuple[str, str, str, bool]]:
    """§3's totals line and §4's prose bullets, both spellings, for each of the seven types.

    `(?<![-\\w])` is load-bearing: without it the `System` pattern also matches the tail of
    `Full-System`, and a run would silently swap the two counts. That is not hypothetical -- it is
    what the first version of this tool did, caught by `--check` before it wrote anything.
    """
    sites = []
    for label in TYPE_DIRS:
        esc = re.escape(label)
        sites.append(("docs/REPORT.md", rf"(?<![-\w]){esc} \*\*(?P<n>\d+)\*\*", f"type:{label}", True))
        # §4 gives a prose bullet to only some types; absent is legal, same as in the guard.
        sites.append(("docs/REPORT.md", rf"^- \*\*{esc} \((?P<n>\d+)\)\*\*", f"type:{label}", False))
    return sites


# --------------------------------------------------------------------------- rewrite

def apply(values: dict[str, int], check_only: bool) -> tuple[list[str], list[str]]:
    changed: list[str] = []
    missing: list[str] = []
    texts = {rel: (ROOT / rel).read_text(encoding="utf-8") for rel in
             {s[0] for s in SITES + _type_sites()} | {s[0] for s in SPLIT_SITES}}

    def substitute(rel: str, spans: list[tuple[int, int, str]]) -> None:
        """Replace the given (start, end, text) spans only. Applied last-first so that rewriting one
        span never shifts the offsets of the ones before it."""
        text = texts[rel]
        for start, end, replacement in sorted(spans, reverse=True):
            text = text[:start] + replacement + text[end:]
        texts[rel] = text

    for rel, pattern, key, required in SITES + _type_sites():
        want = str(values[key])
        found = list(re.finditer(pattern, texts[rel], re.M))
        if not found:
            if required:
                missing.append(f"{rel}: no site matching {pattern!r} -- the sentence moved; update this tool")
            continue
        spans = []
        for m in found:
            if m.group("n") != want:
                changed.append(f"{rel}: {key} {m.group('n')} -> {want}")
            spans.append((*m.span("n"), want))
        substitute(rel, spans)

    for rel, pattern in SPLIT_SITES:
        found = list(re.finditer(pattern, texts[rel]))
        if not found:
            missing.append(f"{rel}: no split matching {pattern!r} -- the sentence moved; update this tool")
            continue
        spans = []
        for m in found:
            skip = int(m.group(2))
            want_pass = values["total"] - skip
            if int(m.group(1)) != want_pass:
                changed.append(f"{rel}: split {m.group(1)}/{skip} -> {want_pass}/{skip}")
            spans.append((*m.span(1), str(want_pass)))
        substitute(rel, spans)

    if not check_only:
        for rel, text in texts.items():
            path = ROOT / rel
            if path.read_text(encoding="utf-8") != text:
                path.write_text(text, encoding="utf-8")
    return changed, missing


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report staleness, change nothing, exit 1 if stale")
    args = ap.parse_args()

    values = measure()
    changed, missing = apply(values, check_only=args.check)

    print(f"measured: {values['total']} collected · {values['functions']} test functions · "
          + " · ".join(f"{label} {values[f'type:{label}']}" for label in TYPE_DIRS))
    for m in missing:
        print(f"  MISSING SITE: {m}")
    if not changed:
        print("  all documented counts already match the suite")
    for c in changed:
        print(f"  {'stale' if args.check else 'updated'}: {c}")

    if missing:
        return 2
    return 1 if (args.check and changed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
