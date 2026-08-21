"""Fill the two gaps `db/seed.py` leaves, so every poster tile can be shot populated.

`db/seed.py` seeds users and forum content — that covers the Forum tile. It has no history
seeder and no message seeder, so a fresh account's **History** shows one heatmap cell and no
trend line, and **Messages** says "No conversations yet". Neither makes a good screenshot, and
neither can be produced by registering an account and clicking around.

This adds, for one demo athlete:

  * ``DAYS`` back-dated daily check-ins  -> a real trend line and a full heatmap
  * a short DM thread with a seeded coach -> a populated conversation

Everything is written through the real ``web/services/db.py`` CRUD, exactly as ``db/seed.py``
does, so each row has the same shape as a user-created one — no hand-built documents that could
drift from the app's contract.

Run it the same way as the seed (Mongo is internal-only, so it has to be on the compose network):

    docker compose run --rm -v "$PWD:/repo" \
      -e MONGO_URI="mongodb://db:27017/worksmarter" \
      --entrypoint sh web -c 'exec python /repo/presentation/showoff/seed-for-screenshots.py'

Then shoot with ``capture-screenshot.mjs``, logging in as the athlete printed at the end.

Idempotent: re-running replaces the same days (``add_history`` is one-row-per-day) and skips the
user if the handle already exists.
"""

import importlib.util
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from werkzeug.security import generate_password_hash

logger = logging.getLogger("screenshot-seed")

REPO = Path(__file__).resolve().parents[2]
DB_PY = REPO / "web" / "services" / "db.py"

ATHLETE = "demo_athlete"
ATHLETE_PW = "demo-seed-pw"          # same throwaway password db/seed.py uses for its clients
COACH = "coach_maya"                 # created by db/seed.py
DAYS = 49                            # matches the "LAST 49 CHECK-INS" the original poster showed

def _vary(day, field, lo, hi):
    """Small deterministic variation in [lo, hi], derived from the day and field.

    Deliberately not `random`: the picture has to be identical every run or the screenshot is not
    reproducible, and a PRNG here would also trip bandit's B311 for no benefit. A multiplicative
    hash gives the same scatter without either problem.
    """
    h = ((day * 2654435761) ^ (field * 40503)) % 2147483647
    return lo + h % (hi - lo + 1)


def _load_db():
    spec = importlib.util.spec_from_file_location("db", str(DB_PY))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _entry(day_offset):
    """One check-in, shaped exactly like a real one (see db.add_history's docstring)."""
    ts = (datetime.now(timezone.utc) - timedelta(days=day_offset)).replace(microsecond=0)
    # readiness drifts rather than jumping, so the trend line reads as a person, not noise
    wave = (day_offset % 14) / 14.0
    fatigue = max(1, min(9, 2 + int(round(5 * wave)) + _vary(day_offset, 1, -1, 1)))
    soreness = max(1, min(9, fatigue + _vary(day_offset, 2, -2, 1)))
    load = max(1, min(9, 4 + _vary(day_offset, 3, -1, 3)))
    sleep = round(max(4.5, min(9.0, 8.0 - wave * 2 + _vary(day_offset, 4, -4, 4) / 10.0)), 1)
    hr = 52 + int(round(8 * wave)) + _vary(day_offset, 5, -2, 2)

    if fatigue >= 7 and soreness >= 6:
        state, proba = "Rest", {"Rest": 0.62, "Moderate": 0.31, "Ready": 0.07}
    elif fatigue >= 5:
        state, proba = "Moderate", {"Moderate": 0.66, "Rest": 0.21, "Ready": 0.13}
    else:
        state, proba = "Ready", {"Ready": 0.78, "Moderate": 0.18, "Rest": 0.04}

    return {
        "timestamp": ts.isoformat(),
        "metrics": {"sleep_hours": sleep, "resting_hr": hr,
                    "fatigue": fatigue, "soreness": soreness, "training_load": load},
        "assessment": state,
        "proba": proba,
        "calories": 2909 if state != "Rest" else 2665,
        "recommendations": {
            "Ready": ["Readiness is high; continue with the planned session using normal progression."],
            "Moderate": ["Readiness is moderate; use a controlled session and adjust if symptoms worsen."],
            "Rest": ["Readiness is low; prioritise recovery and keep today easy or off."],
        }[state],
    }


THREAD = [
    (COACH,   "Hey! Saw your leg-day PR 🔥 how's recovery feeling today?"),
    (ATHLETE, "Thanks Maya! A little sore, but readiness still says Moderate so I'll keep it steady."),
    (COACH,   "Smart. Moderate = maintain — don't chase another PR two days running."),
    (ATHLETE, "Exactly what the app suggested. Deload next week?"),
    (COACH,   "Yes — let your Ready days come back up first. You're trending really well 💪"),
]


def main():
    from pymongo import MongoClient          # same access path as db/seed.py

    uri = os.environ.get("MONGO_URI", "mongodb://db:27017/worksmarter")
    db_mod = _load_db()
    client = MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        db = client.get_default_database()

        created = db_mod.create_user(db, ATHLETE, generate_password_hash(ATHLETE_PW),
                                     email=f"{ATHLETE}@example.com", display_name="Dana Levi")
        logger.info("athlete: %s (%s)", ATHLETE, "created" if created else "already existed")

        for offset in range(DAYS):
            db_mod.add_history(db, ATHLETE, _entry(offset))
        logger.info("history: %d back-dated check-ins", DAYS)

        if not db_mod.message_list_conversation(db, ATHLETE, COACH):
            for sender, body in THREAD:
                db_mod.message_send(db, sender, COACH if sender == ATHLETE else ATHLETE, body)
            logger.info("messages: %d-message thread with %s", len(THREAD), COACH)
        else:
            logger.info("messages: thread already present - skipped")

        logger.info("log in as  %s / %s", ATHLETE, ATHLETE_PW)
    finally:
        client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
