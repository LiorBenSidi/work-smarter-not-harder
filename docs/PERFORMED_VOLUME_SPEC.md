# Proposed: logging performed training volume (`features["performed"]`)

**Status: draft, not sent to the team.** This is a proposal from the AI side for what `web`/`db`
would need to build to close #276 P7 / #528 item 2 — it is not a request to build it yet, and
nothing here is final. Flagging the sync point in `docs/DESIGN.md` §3 as PROPOSED; this file is the
detail behind that flag.

## Why this exists

`ai/recommendations.py::_program_recommendations` (the undertrained-muscle-group balance analysis)
is fully built and unit-tested, but has never had a real input in production. It was originally
meant to receive the athlete's actual training program; nothing in `web` ever sent one. Feeding it
the *prescribed* plan `generate_workout_days` produces instead doesn't work either — that plan is
balanced by construction (every split/frequency/equipment combination it can produce already lands
inside the analysis's own thresholds), so it can never fire, and a balance check against a plan the
same engine just wrote would be circular regardless. The analysis needs to see what the athlete
**actually did**.

## What `/predict` would accept

A new, optional field on the existing `POST /predict` request, alongside `features`' current keys:

```json
{
  "features": {
    "...": "...(existing fields, unchanged)",
    "performed": [
      {"muscle_group": "chest", "sets": 18},
      {"muscle_group": "back", "sets": 6}
    ]
  }
}
```

- **Shape:** a flat list of `{"muscle_group": <str>, "sets": <number>}`. `ai/recommendations.py`
  already accepts this exact shape (and a `{"weekly_sets": {...}}` dict form, for flexibility) —
  no `ai`-side change needed once this is sent.
- **Aggregation window: trailing 7 days.** The analysis's thresholds (6–20 sets/muscle-group/week,
  chest:back ratio 0.67–1.5) are already calibrated for a weekly cadence — a 7-day window means
  `ai/` needs no threshold recalibration. A 14-day window is possible but would need new,
  unvalidated thresholds.
- **Muscle groups:** the same 10 used throughout `ai/exercise_catalog.py` — `chest, back,
  shoulders, biceps, triceps, quads, hamstrings, glutes, calves, core`. Anything outside this set
  is silently ignored by `_program_recommendations` today (unrecognized keys just never
  accumulate volume), so an exact-match isn't strictly required, but using the same 10 names
  means every logged set is actually counted.
- **Missing/absent is fine.** Like `program` before it, `performed` is optional — omitting it
  just means the balance analysis contributes nothing to that `/predict` response, the same
  graceful-degradation behavior every other optional input already has.

## What logging it would need (web/db's call, not ai's)

Two ways to collect this, from simplest to most work — a proposal to weigh, not a mandate:

**Option 1 — log at the muscle-group level directly.** After a session, the athlete records sets
per muscle group they trained ("Chest: 4 sets, Back: 3 sets, ..."), not per exercise. Simplest UI,
no new coupling: `web` never needs to know about `ai/exercise_catalog.py`'s exercise list or its
muscle-group mapping, so the containers stay as decoupled as they are today.

**Option 2 — log per exercise, map to muscle group after.** Richer data (what was actually done,
not just a bucket count), but needs `web` to either duplicate `ai/exercise_catalog.py`'s
exercise→muscle-group mapping or have some other source of truth for it — a new cross-container
dependency that doesn't exist today. Only worth it if per-exercise history has value beyond
feeding this one analysis.

**Suggested storage** (illustrative, `db`'s call): a `performed_sets` collection or an extension
of the existing check-in flow — `{username, date, muscle_group, sets}` per logged entry (option 1)
or `{username, date, exercise_name, sets}` (option 2, would need the mapping question above
resolved first). `web` would aggregate the trailing 7 days into the flat shape above before adding
it to the `/predict` request body, the same place `history` is already assembled today
(`web/routes/dashboard.py`).

## What's explicitly not proposed here

No new `ai/` work is described in this file — `ai/recommendations.py` already reads
`features.get("performed")` as of today, ready the moment `web` starts sending it. Everything above
is entirely `web`/`db` scope.
