#!/usr/bin/env bash
# Work Smarter, Not Harder — populate the RUNNING stack with demo content (optional).
#
# Usage:  ./seed.sh          (run AFTER ./install.sh has the 3 containers up)
#
# Seeds a few fake clients plus a forum with posts, comments and likes, so a fresh
# install shows a populated app instead of an empty room. Idempotent: re-running
# adds nothing if the forum already has content. A brand-new database is empty by
# design (real product behaviour) — this is a deliberate demo/review tool.
#
# Every failure below prints WHAT went wrong and HOW to fix it — a reviewer should
# never have to guess.
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
  echo "ERROR: Docker is required but was not found." >&2
  echo "       Fix: install Docker Desktop — https://docs.docker.com/get-docker/" >&2
  exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
  echo "ERROR: Docker Compose v2 is required ('docker compose', not 'docker-compose')." >&2
  echo "       Fix: it ships with Docker Desktop; on Linux install the compose plugin." >&2
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: the Docker daemon is not running." >&2
  echo "       Fix: start Docker Desktop, wait until it says 'running', then re-run ./seed.sh" >&2
  exit 1
fi

if [ -z "$(docker compose ps --status running -q db 2>/dev/null)" ]; then
  echo "ERROR: the 'db' container isn't running, so there is nothing to seed." >&2
  echo "       Fix: start the stack first, then re-run this script:" >&2
  echo "            ./install.sh          (or:  docker compose up -d --build)" >&2
  exit 1
fi

echo "Seeding demo content into the running database…"
# db/ isn't baked into the web image, so mount the repo and run the seed with the web
# image's interpreter (it already has pymongo + werkzeug). It reaches the database over
# the compose network; MONGO_URI has no auth in local dev.
#
# The `[ -f /repo/db/seed.py ]` guard catches the one non-obvious failure mode: if the
# repo sits on a path your Docker does NOT share with its VM (e.g. /tmp under
# Rancher/Lima, or any folder outside Docker Desktop's File-sharing list), the bind
# mount silently succeeds but is EMPTY. Without the guard you'd get a bare
# "python: can't open file '/repo/db/seed.py'" and no clue why.
docker compose run --rm \
  -v "$PWD:/repo" \
  -e MONGO_URI="mongodb://db:27017/worksmarter" \
  -e HOST_REPO="$PWD" \
  --entrypoint sh web -c '
    if [ ! -f /repo/db/seed.py ]; then
      echo "ERROR: Docker could not share this project folder into the container," >&2
      echo "       so the seed script is not visible inside it." >&2
      echo "       Folder: $HOST_REPO" >&2
      echo "       Fix (either one):" >&2
      echo "         1) Move the project under your home directory, e.g." >&2
      echo "              ~/work-smarter-not-harder   — then re-run ./seed.sh" >&2
      echo "         2) Or allow this folder in Docker Desktop ->" >&2
      echo "              Settings -> Resources -> File sharing, restart Docker, re-run." >&2
      exit 1
    fi
    exec python /repo/db/seed.py'

echo
echo "Done — open http://localhost:8000 ; the forum now has demo posts."
echo "Log in as a seeded client (e.g. coach_maya) with the demo password: demo-seed-pw"
