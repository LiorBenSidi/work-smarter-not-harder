#!/usr/bin/env bash
# Work Smarter, Not Harder — one-command local run.
#
# Usage:  ./install.sh
# Needs:  Docker Desktop (macOS/Windows) or Docker Engine + Compose v2 (Linux).
#         Nothing else — Python, the AI model, and MongoDB all run in containers.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: Docker is required. Install it from https://docs.docker.com/get-docker/" >&2
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: Docker Compose v2 is required (bundled with Docker Desktop; 'docker compose' plugin on Linux)." >&2
  exit 1
fi

# First run: create a local .env (gitignored) from the template.
if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example."
fi

echo
echo "Building and starting the 3-container stack (web · ai · db)…"
echo "When it is up, open  ->  http://localhost:8000   (health: /health)"
echo "Register a new account; with no SMTP set, one-time codes appear on screen and in the logs."
echo "Stop with Ctrl-C, then 'docker compose down'."
echo

exec docker compose up --build
