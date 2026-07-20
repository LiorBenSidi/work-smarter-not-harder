"""Repo-integrity guards — these are permanent, not a scaffold awaiting replacement.

The filename is historical (they were the first tests written). They stayed because what they check
never stops mattering: `test_env_secrets_not_committed` shells out to `git ls-files .env` and goes red
the moment anyone commits a secret — deliberately asking git rather than the filesystem, so a
developer's own gitignored `.env` is not a false positive.

These guard the project's required structure and a cardinal course rule (never commit secrets).
They run in CI on every PR (see .github/workflows/ci.yml) and genuinely fail if an invariant breaks.
"""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # tests/Unit_Tests/ -> repo root


def test_container_dirs_exist():
    for d in ("web", "ai", "tests"):
        assert (ROOT / d).is_dir(), f"missing required directory: {d}/"


def test_five_test_type_dirs_exist():
    for name in ("Unit_Tests", "Integration_Tests", "System_Tests", "Stress_Tests", "Security_Tests"):
        assert (ROOT / "tests" / name).is_dir(), f"missing test-type dir: tests/{name}/"


def test_submitted_proposal_present():
    assert (ROOT / "docs" / "PROPOSAL.md").is_file(), "the submitted proposal must live at docs/PROPOSAL.md"


def test_env_secrets_not_committed():
    # .env must never be tracked by git — secrets stay local (only .env.example is committed).
    # Checked via git (not the filesystem) so a developer's local, gitignored .env is not a false failure.
    tracked = subprocess.run(
        ["git", "ls-files", ".env"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()
    assert tracked == "", ".env must never be committed — keep secrets local (.env.example only)"
