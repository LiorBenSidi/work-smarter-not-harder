#!/usr/bin/env bash
# Work Smarter, Not Harder — one-command local run.
#
# Usage:  ./install.sh            start the stack (foreground, Ctrl-C stops it)
#         ./install.sh --seed     start it AND fill it with demo data first
#
#         BOTH run in the FOREGROUND and Ctrl-C stops the stack. If you'd rather it kept
#         running while you use the terminal, take the detached route instead:
#             cp .env.example .env && docker compose up --build -d && ./seed.sh
#
# Needs:  Docker Desktop (macOS/Windows) or Docker Engine + Compose v2 (Linux).
#         Nothing else — Python, the AI model, and MongoDB all run in containers.
set -euo pipefail
cd "$(dirname "$0")"

SEED=0
case "${1:-}" in
  --seed) SEED=1 ;;
  "")     ;;
  *)      echo "usage: ./install.sh [--seed]" >&2; exit 2 ;;
esac

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
if [ "$SEED" -eq 1 ]; then
  echo "Then it will be seeded with demo data (--seed)."
else
  echo "Want demo content (15 athletes, history, forum, messages)? Re-run as:  ./install.sh --seed"
  echo "                                       or, once it is up, in another terminal:  ./seed.sh"
fi
echo "This runs in the FOREGROUND — Ctrl-C stops the stack (then 'docker compose down' to clean up)."
echo "Prefer it detached?  cp .env.example .env && docker compose up --build -d && ./seed.sh"
echo

if [ "$SEED" -eq 0 ]; then
  exec docker compose up --build
fi

# --seed: bring the stack up DETACHED so the seed can run, then re-attach. `compose up` on an
# already-running stack attaches to it, so Ctrl-C still stops everything exactly as it does without
# the flag — only the ordering changes. Seeding needs a running db, and `compose run` (inside
# seed.sh) waits for db's healthcheck on its own, so no sleep is needed here.
docker compose up --build -d
echo
./seed.sh
echo
echo "Seeded. Re-attaching — Ctrl-C stops the stack."
echo
exec docker compose up
