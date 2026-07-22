#!/usr/bin/env bash
# Work Smarter, Not Harder — populate the RUNNING stack with demo content (optional).
#
# Usage:  ./seed.sh          (run AFTER ./install.sh has the 3 containers up)
#
# Seeds a few fake clients plus a forum with posts, comments and likes, so a fresh
# install shows a populated app instead of an empty room. Idempotent: re-running
# adds nothing if the forum already has content. A brand-new database is empty by
# design (real product behaviour) — this is a deliberate demo/review tool.
set -euo pipefail
cd "$(dirname "$0")"

if [ -z "$(docker compose ps --status running -q db 2>/dev/null)" ]; then
  echo "ERROR: the 'db' container isn't running. Start the stack first:" >&2
  echo "         ./install.sh        (or: docker compose up -d --build)" >&2
  exit 1
fi

echo "Seeding demo content into the running database…"
# db/ isn't baked into the web image, so mount the repo and run the seed with the
# web image's interpreter (it already has pymongo + werkzeug). Talks to the db
# service over the compose network. MONGO_URI has no auth in local dev.
docker compose run --rm -v "$PWD:/repo" \
  -e MONGO_URI="mongodb://db:27017/worksmarter" \
  web python /repo/db/seed.py

echo
echo "Done — open http://localhost:8000 and the forum now has demo posts."
echo "Log in as a seeded client with the demo password (see SEED_PASSWORD in db/seed.py)."
