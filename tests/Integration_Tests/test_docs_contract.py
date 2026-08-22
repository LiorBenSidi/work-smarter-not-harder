"""The graded documents have to describe the suite that actually exists. OWNER: Lior.

Every suite size in REPORT.md, README.md and SUBMISSION.md is hand-written, so any change to the tests
silently invalidates them — and nothing in the repo noticed. The numbers are what a reviewer checks
first, and a report that claims a count the repo cannot produce undermines every other claim in it.

This does not police prose. It reads the one number each document states as the suite's size and
compares it to a real collection.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Each entry: the file, and a regex whose first group is the collected-case count it claims. Anchored on
# the surrounding words so a different number in the same file (a percentage, a year, a section count)
# can never be picked up by accident.
# Appended to every staleness failure below. Without it the message names the wrong number but not
# the fix, and the obvious response -- hand-editing the figure -- is the habit that produced the drift
# in the first place. These numbers are generated; the message has to say so where it is read.
FIX = ("\n\nThese numbers are GENERATED, not typed. Do not hand-edit them:\n"
       "    python scripts/sync_counts.py && git add README.md docs/REPORT.md docs/SUBMISSION.md")

CLAIMS = [
    ("docs/REPORT.md", r"\*\*Suite at this snapshot:\*\* \*\*(\d+) checks"),
    ("docs/REPORT.md", r"\*\*(\d+) automated checks across the seven"),
    ("docs/REPORT.md", r"(\d+) collected cases come from"),
    ("README.md", r"Suite: \*\*(\d+) collected\*\*"),
    ("docs/SUBMISSION.md", r"`REPORT\.md`, (\d+) tests"),
]


def _collected_now():
    """Collect the whole suite in a separate process, so this is the real number and not this run's selection."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"collection failed:\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    return sum(1 for line in proc.stdout.splitlines() if "::" in line)


def test_the_graded_documents_state_the_suite_size_the_repo_actually_has():
    """A reviewer checks the headline number before anything else, and each of these is typed by hand — so a single added or removed test leaves three graded documents asserting a suite that cannot be produced, with nothing to catch it.

    The failure names the file and both numbers, because the fix is always the same edit.
    """
    actual = _collected_now()
    wrong = []
    for rel, pattern in CLAIMS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        found = re.search(pattern, text)
        assert found, f"{rel}: the suite-size sentence matching {pattern!r} is gone — update this guard with it"
        claimed = int(found.group(1))
        if claimed != actual:
            wrong.append(f"{rel} says {claimed}, the suite collects {actual}")
    assert not wrong, "the graded docs are behind the suite:\n  " + "\n  ".join(wrong) + FIX


# Each entry: where the split is written, and a regex giving (passed, skipped). Both environments are
# stated in the report — locally some suites are env-gated, in CI the `mongo:7` service unskips them —
# and a split that does not add up to the total is the same drift showing in a place the total does not.
SPLITS = [
    ("docs/REPORT.md", r"the current suite is \*\*(\d+) pass,\n(\d+) skip"),
    ("docs/REPORT.md", r"suite is \*\*(\d+) pass, (\d+) skip\*\*"),
    ("README.md", r"Suite: \*\*\d+ collected\*\* \((\d+) pass / (\d+) environment-gated\)"),
    ("docs/SUBMISSION.md", r"\((\d+) pass / (\d+) env-gated in CI\)"),
]


def test_every_pass_skip_split_in_the_docs_adds_up_to_the_suite():
    """The report states two different pass/skip splits — one local, one for CI where the mongo service unskips the DB-backed suites — and a split that does not sum to the collected total is wrong no matter which environment produced it.

    This is the half the headline count cannot catch: a total refreshed while the pass/skip line beneath
    it is left behind produces a document that contradicts itself in a single sentence.
    Arithmetic only — it says nothing about whether those tests pass, just that the figures are possible.
    """
    actual = _collected_now()
    wrong = []
    for rel, pattern in SPLITS:
        text = (ROOT / rel).read_text(encoding="utf-8")
        found = re.search(pattern, text)
        assert found, f"{rel}: the pass/skip sentence matching {pattern!r} is gone — update this guard with it"
        passed, skipped = int(found.group(1)), int(found.group(2))
        if passed + skipped != actual:
            wrong.append(f"{rel}: {passed} pass + {skipped} skip = {passed + skipped}, but the suite collects {actual}")
    assert not wrong, "a stated split cannot be produced by this suite:\n  " + "\n  ".join(wrong) + FIX


def test_the_report_states_the_number_of_test_functions_it_can_count():
    """The report separates collected cases from hand-written test functions — the gap between them is how it explains parametrization — and that second number drifts on exactly the same edits as the first.

    It is counted the way the report itself says it is counted, so the sentence and the measurement can
    never mean two different things. This one is worth its own case because it is the figure a reader
    uses to judge whether the suite is broad or merely parametrized wide.
    """
    written = sum(
        1
        for path in (ROOT / "tests").rglob("*.py")
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line.startswith("def test_")
    )
    text = (ROOT / "docs/REPORT.md").read_text(encoding="utf-8")
    found = re.search(r"come from \*\*(\d+) test\nfunctions\*\*", text)
    assert found, "REPORT.md no longer states a test-function count — update this guard with it"
    claimed = int(found.group(1))
    assert claimed == written, f"docs/REPORT.md says {claimed} test functions; tests/ defines {written}" + FIX


# --------------------------------------------------------------------- per-type counts (#527)
# The headline total above was guarded; the PER-TYPE breakdown was not — and REPORT.md states it TWICE,
# once as the §3 totals line and again as the §4 bullets, with §4 asserting in prose that the two are
# "the same ones tabulated in §3 ... not estimates". They had drifted to Unit 381 / Integration 384
# against a real 546 / 433: two sections of one graded report giving different numbers for the same
# thing, with one of them denying it. Falsifiable by a grader in under a minute (#527).
#
# Guarding both spellings is the point. Guarding only one lets the other rot exactly as it did.

TYPE_DIRS = {
    "Unit": "Unit_Tests", "Integration": "Integration_Tests", "Negative": "Negative_Tests",
    "System": "System_Tests", "Full-System": "Full_System_Tests", "Security": "Security_Tests",
    "Stress": "Stress_Tests",
}


def _collected_in(directory):
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", f"tests/{directory}", "--collect-only", "-q",
         "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"collecting tests/{directory} failed:\n{proc.stdout[-2000:]}"
    return sum(1 for line in proc.stdout.splitlines() if "::" in line)


def test_the_reports_per_type_totals_line_matches_the_suite():
    """§3's "Totals by type" line is the table a grader cross-checks against `--collect-only`."""
    text = (ROOT / "docs/REPORT.md").read_text(encoding="utf-8")
    wrong = []
    for label, directory in TYPE_DIRS.items():
        found = re.search(rf"{re.escape(label)} \*\*(\d+)\*\*", text)
        assert found, f"§3's totals line no longer names {label} — update this guard with it"
        actual = _collected_in(directory)
        if int(found.group(1)) != actual:
            wrong.append(f"§3 says {label} {found.group(1)}, tests/{directory} collects {actual}")
    assert not wrong, "REPORT.md §3's per-type totals are behind the suite:\n  " + "\n  ".join(wrong) + FIX


def test_the_reports_per_type_prose_agrees_with_its_own_totals_line():
    """§4 describes each type as "- **Unit (N)** — ..." and claims those figures ARE §3's. This is the
    guard that would have caught #527: the two spellings must agree with each other AND with the repo."""
    text = (ROOT / "docs/REPORT.md").read_text(encoding="utf-8")
    wrong = []
    for label, directory in TYPE_DIRS.items():
        found = re.search(rf"^- \*\*{re.escape(label)} \((\d+)\)\*\*", text, re.M)
        if not found:
            continue                      # not every type gets its own §4 bullet
        actual = _collected_in(directory)
        if int(found.group(1)) != actual:
            wrong.append(f"§4 says {label} {found.group(1)}, tests/{directory} collects {actual}")
    assert not wrong, "REPORT.md §4's per-type prose is behind the suite:\n  " + "\n  ".join(wrong) + FIX

# --------------------------------------------------------------------- the generator's own anchors


def test_the_generator_still_recognises_every_sentence_it_maintains():
    """`scripts/sync_counts.py` writes these numbers; the guards above only check the result.

    Three of the sites it maintains are ones no guard above asserts the existence of -- "the two
    supporting directories complete the N", SUBMISSION's "current — **N tests**", and the
    `pytest -q` comment. Reword any of those and the generator silently stops maintaining it: the
    number then rots with nothing watching, which is exactly how docs/DEMO_RUNBOOK.md reached 1412
    against a real 1461.

    A generator maintaining nothing looks identical to one with nothing to do, so this asserts the
    difference. `--check` exits 2 when a required anchor has moved. Read-only -- it reports, it does
    not write.
    """
    proc = subprocess.run(
        [sys.executable, "scripts/sync_counts.py", "--check"],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode != 2, (
        "scripts/sync_counts.py can no longer find a sentence it is supposed to keep current, so a "
        "documented count is now unmaintained. Re-anchor it in that script's SITES/SPLIT_SITES.\n"
        + proc.stdout
    )
    # Exit 1 is the ordinary "stale" case, but the script also exits 1 when collection itself fails,
    # when a tests/ directory exists that TYPE_DIRS does not name, or on any bug in it -- and those
    # report through stderr. Showing both streams means the failure explains itself instead of
    # advising a command that would not help.
    assert proc.returncode == 0, (
        f"scripts/sync_counts.py --check failed (exit {proc.returncode}). If the counts are simply "
        "stale, regenerate them; if the output below says otherwise, fix that instead.\n"
        f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
    )
