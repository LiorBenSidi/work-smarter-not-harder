"""Unit tests for db/backup.sh — the Mongo backup script's contract. OWNER: Lior.

We don't run a real mongodump here; we pin the script's guardrail: it must exist, be executable, and
**fail fast with a clear message** when MONGO_URI is unset (before it ever touches the database).
"""
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "db" / "backup.sh"


def test_backup_script_exists_and_is_executable():
    assert SCRIPT.is_file(), "db/backup.sh is missing"
    if sys.platform == "win32":
        # The Unix executable bit isn't a Windows concept (git may not preserve it on checkout); the
        # script's +x only matters on the Linux deploy target / CI, which asserts it below.
        pytest.skip("exec bit is Unix-only; verified on Linux CI")
    assert SCRIPT.stat().st_mode & 0o111, "db/backup.sh must be executable"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="backup.sh runs under bash; on Windows 'bash' resolves to the WSL shim (no distro), so it "
           "can't run locally — the fail-fast-without-MONGO_URI contract is verified on Linux CI",
)
def test_backup_requires_mongo_uri():
    # with no MONGO_URI the script must exit non-zero and name the missing var — before any mongodump
    result = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}
    )
    assert result.returncode != 0
    assert "MONGO_URI" in (result.stderr + result.stdout)
