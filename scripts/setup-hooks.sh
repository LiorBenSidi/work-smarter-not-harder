#!/usr/bin/env sh
# One-time setup: point git at this repo's shared hooks (.githooks/) instead of .git/hooks.
# Safe to re-run. Installs NOTHING (tool install is a separate, explicit step below).
set -e

# Must run inside the clone. Capture the root explicitly and abort LOUDLY if we're not in a
# git repo -- a bare `cd "$(git rev-parse --show-toplevel)"` would silently `cd ""` (a no-op
# that "succeeds" under set -e) and then configure the WRONG directory while printing OK.
root=$(git rev-parse --show-toplevel) || {
  echo "setup-hooks FAILED: not inside a git repository -- cd into your clone and re-run." >&2
  exit 1
}
cd "$root"

git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true

# Only claim success if the config actually took (don't print OK on a silent miss).
if [ "$(git config --get core.hooksPath)" != ".githooks" ]; then
  echo "setup-hooks FAILED: could not set core.hooksPath to .githooks." >&2
  exit 1
fi

echo "OK: core.hooksPath = .githooks (shared git hooks enabled for this clone)"
echo
echo "Next, one-time, in your ACTIVATED project venv, install the pinned tools:"
echo "    pip install -r requirements-dev.txt"
echo
echo "From then on:  ruff + bandit run on 'git commit', pytest runs on 'git push'."
echo "Emergency bypass: add --no-verify (CI still gates every PR)."
