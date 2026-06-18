#!/usr/bin/env sh
# One-time setup: point git at this repo's shared hooks (.githooks/) instead of .git/hooks.
# Safe to re-run. Installs NOTHING (tool install is a separate, explicit step below).
set -e
cd "$(git rev-parse --show-toplevel)"

git config core.hooksPath .githooks
chmod +x .githooks/* 2>/dev/null || true

echo "OK: core.hooksPath = .githooks (shared git hooks enabled for this clone)"
echo
echo "Next, one-time, in your ACTIVATED project venv, install the pinned tools:"
echo "    pip install -r requirements-dev.txt"
echo
echo "From then on:  ruff + bandit run on 'git commit', pytest runs on 'git push'."
echo "Emergency bypass: add --no-verify (CI still gates every PR)."
