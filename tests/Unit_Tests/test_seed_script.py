"""Unit tests for seed.sh — the demo-seeding wrapper's contract. OWNER: Elad.

`db/seed.py`'s own logic is covered by `test_seed.py`; this file covers the **shell wrapper** that has to
get the repo into the container before any of that Python can run. It never talks to Docker: a fake `docker`
is put first on `PATH`, so the script's real invocation is captured and asserted.

The invocation is worth pinning because it broke on a whole platform without breaking anywhere else (#580):
Git Bash rewrites *both* halves of a `-v "$PWD:/repo"` argument into Windows paths, so the repo mounted at
`C:/repo`, `/repo` stayed empty, and `./seed.sh` failed on Windows from every folder — including the home
directory its own error message recommends. `MSYS_NO_PATHCONV` / `MSYS2_ARG_CONV_EXCL` suppress that
rewrite; they are unset and ignored on macOS/Linux, which is why CI cannot notice them going missing.
"""
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "seed.sh"

# A `docker` that answers seed.sh's four preflight checks and records the real `compose run` call.
FAKE_DOCKER = """#!/usr/bin/env bash
case "$1 $2" in
  "compose version") exit 0 ;;
  "info ")           exit 0 ;;
esac
if [ "$1 $2 $3" = "compose ps --status" ]; then
  echo "fake-db-container-id"   # pretend the db container is up, so seeding proceeds
  exit 0
fi
if [ "$1" = "compose" ] && [ "$2" = "run" ]; then
  {
    echo "MSYS_NO_PATHCONV=${MSYS_NO_PATHCONV-<unset>}"
    echo "MSYS2_ARG_CONV_EXCL=${MSYS2_ARG_CONV_EXCL-<unset>}"
    for arg in "$@"; do echo "ARG=$arg"; done
  } > "$SEED_CALL_LOG"
  exit 0
fi
exit 0
"""


@pytest.fixture
def seed_run(tmp_path):
    """Run seed.sh against a fake docker and return the recorded call as (env, args)."""
    if sys.platform == "win32":
        pytest.skip("seed.sh runs under bash; on Windows 'bash' is the WSL shim — verified on Linux CI")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "docker"
    fake.write_text(FAKE_DOCKER)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    log = tmp_path / "call.log"

    env = dict(os.environ)
    env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
    env["SEED_CALL_LOG"] = str(log)
    env.pop("MSYS_NO_PATHCONV", None)
    env.pop("MSYS2_ARG_CONV_EXCL", None)

    result = subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True, env=env)
    assert result.returncode == 0, f"seed.sh failed: {result.stderr}"
    assert log.exists(), "seed.sh never reached 'docker compose run'"

    # The recording is the two env lines, then one "ARG=" line per argument. The arguments cannot be read
    # line-by-line: the last one is the container-side shell script and is many lines long, so a per-line
    # parse reads its body as further env entries (and blows up on the first line with no "=" in it).
    env_text, _, args_text = log.read_text().partition("ARG=")
    call_env = dict(line.split("=", 1) for line in env_text.splitlines() if line)
    args = [a.rstrip("\n") for a in args_text.split("\nARG=")] if args_text else []
    return call_env, args


def test_seed_mounts_the_repo_at_slash_repo(seed_run):
    """The repo is bind-mounted at /repo, which is where the container-side command looks for the seed script."""
    _, args = seed_run
    assert "-v" in args, f"no bind mount in the docker call: {args}"
    mount = args[args.index("-v") + 1]
    host, _, container = mount.rpartition(":")
    assert container == "/repo", f"the seed script is read from /repo, but the mount targets {container!r}"
    assert Path(host).resolve() == ROOT, f"the mount source should be the repo root, got {host!r}"


def test_seed_suppresses_git_bash_path_rewriting(seed_run):
    """Both MSYS guards reach docker, or the mount silently lands at C:/repo on Windows and seeding fails there.

    Nothing else in the repo catches this: on macOS/Linux the two variables are inert, so the mount is
    correct with or without them and every non-Windows run stays green while Windows stays broken (#580).
    """
    call_env, _ = seed_run
    assert call_env.get("MSYS_NO_PATHCONV") == "1", (
        "MSYS_NO_PATHCONV=1 must be set for the mount: without it Git Bash rewrites '/repo' to 'C:/repo'"
    )
    assert call_env.get("MSYS2_ARG_CONV_EXCL") == "*", (
        "MSYS2_ARG_CONV_EXCL='*' must be set for the mount: it excludes every argument from the rewrite"
    )
