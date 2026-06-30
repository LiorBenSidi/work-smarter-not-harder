"""Unit tests for db/backup.sh — the Mongo backup script's contract. OWNER: Lior.

We don't run a real mongodump here; we pin the script's guardrail: it must exist, be executable, and
**fail fast with a clear message** when MONGO_URI is unset (before it ever touches the database).
"""
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "db" / "backup.sh"


def test_backup_script_exists_and_is_executable():
    assert SCRIPT.is_file(), "db/backup.sh is missing"
    assert SCRIPT.stat().st_mode & 0o111, "db/backup.sh must be executable"


def test_backup_requires_mongo_uri():
    # with no MONGO_URI the script must exit non-zero and name the missing var — before any mongodump
    result = subprocess.run(
        ["bash", str(SCRIPT)], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"}
    )
    assert result.returncode != 0
    assert "MONGO_URI" in (result.stderr + result.stdout)
