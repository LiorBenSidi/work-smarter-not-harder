"""Exercise catalog (F5 prerequisite) — the data the workout generator selects from.

Pure static data, no I/O, no external dataset: PMData (the readiness model's source) is
triathlon/endurance session logging (sleep, fatigue, soreness, sRPE) and carries no exercise-level
info — verified by inspecting the columns the training pipeline reads (`scripts/build_training_dataset.py`).
So this catalog is hand-curated against general strength-training guidelines, not derived from PMData.

Each entry:
    name          -- display name
    muscle_group  -- primary muscle trained (lowercase); MUST match the vocabulary
                     `_program_recommendations` in recommendations.py already sums volume over
                     (chest/back are special-cased there; any other lowercase string is accepted
                     generically)
    pattern       -- "push" | "pull" | "legs" | "core" -- maps an exercise onto a split day's focus
                     (e.g. an Upper/Push day pulls from pattern == "push")
    equipment     -- single item from EQUIPMENT below; must stay in sync with
                     web/routes/profile.py's EQUIPMENT tuple (the two containers don't share
                     imports, so this is a duplicated contract by convention, like `/predict`'s
                     feature order)
    is_compound   -- True for multi-joint lifts; used to order a day's exercises compound-first

Sets/reps are NOT stored here -- the generator derives them from the athlete's goal at selection
time (ai/recommendations.py already does the equivalent for calorie/recovery advice), not from
per-exercise catalog data.
"""

from __future__ import annotations

# Must match web/routes/profile.py's EQUIPMENT tuple exactly.
EQUIPMENT = ("bodyweight", "dumbbell", "barbell", "kettlebell", "machine", "bands", "pullup_bar")

MUSCLE_GROUPS = (
    "chest", "back", "shoulders", "biceps", "triceps",
    "quads", "hamstrings", "glutes", "calves", "core",
)

PATTERNS = ("push", "pull", "legs", "core")

EXERCISE_CATALOG = [
    # --- chest (push) ---
    {"name": "Barbell bench press", "muscle_group": "chest", "pattern": "push", "equipment": "barbell", "is_compound": True},
    {"name": "Dumbbell bench press", "muscle_group": "chest", "pattern": "push", "equipment": "dumbbell", "is_compound": True},
    {"name": "Incline dumbbell press", "muscle_group": "chest", "pattern": "push", "equipment": "dumbbell", "is_compound": True},
    {"name": "Machine chest press", "muscle_group": "chest", "pattern": "push", "equipment": "machine", "is_compound": True},
    {"name": "Push-up", "muscle_group": "chest", "pattern": "push", "equipment": "bodyweight", "is_compound": True},
    {"name": "Band chest press", "muscle_group": "chest", "pattern": "push", "equipment": "bands", "is_compound": True},
    {"name": "Dumbbell flye", "muscle_group": "chest", "pattern": "push", "equipment": "dumbbell", "is_compound": False},
    {"name": "Machine chest flye (Pec-Deck)", "muscle_group": "chest", "pattern": "push", "equipment": "machine", "is_compound": False},
    {"name": "Band chest flye", "muscle_group": "chest", "pattern": "push", "equipment": "bands", "is_compound": False},
    {"name": "Decline barbell bench press", "muscle_group": "chest", "pattern": "push", "equipment": "barbell", "is_compound": True},
    {"name": "Decline dumbbell bench press", "muscle_group": "chest", "pattern": "push", "equipment": "dumbbell", "is_compound": True},
    {"name": "Low cable fly (Cable)", "muscle_group": "chest", "pattern": "push", "equipment": "machine", "is_compound": False},
    {"name": "High cable fly (Cable)", "muscle_group": "chest", "pattern": "push", "equipment": "machine", "is_compound": False},
    {"name": "Chest dip", "muscle_group": "chest", "pattern": "push", "equipment": "bodyweight", "is_compound": True},

    # --- back (pull) ---
    {"name": "Pull-up", "muscle_group": "back", "pattern": "pull", "equipment": "pullup_bar", "is_compound": True},
    {"name": "Lat pulldown", "muscle_group": "back", "pattern": "pull", "equipment": "machine", "is_compound": True},
    {"name": "Barbell bent-over row", "muscle_group": "back", "pattern": "pull", "equipment": "barbell", "is_compound": True},
    {"name": "Dumbbell one-arm row", "muscle_group": "back", "pattern": "pull", "equipment": "dumbbell", "is_compound": True},
    {"name": "Band seated row", "muscle_group": "back", "pattern": "pull", "equipment": "bands", "is_compound": True},
    {"name": "Superman", "muscle_group": "back", "pattern": "pull", "equipment": "bodyweight", "is_compound": False},
    {"name": "Seated cable row", "muscle_group": "back", "pattern": "pull", "equipment": "machine", "is_compound": True},
    {"name": "T-Bar row", "muscle_group": "back", "pattern": "pull", "equipment": "barbell", "is_compound": True},
    {"name": "Cable pullover (Cable)", "muscle_group": "back", "pattern": "pull", "equipment": "machine", "is_compound": False},
    {"name": "Machine pullover", "muscle_group": "back", "pattern": "pull", "equipment": "machine", "is_compound": False},
    {"name": "Lat pulldown close grip", "muscle_group": "back", "pattern": "pull", "equipment": "machine", "is_compound": True},

    # --- shoulders (push, plus a rear-delt pull variant) ---
    {"name": "Barbell overhead press", "muscle_group": "shoulders", "pattern": "push", "equipment": "barbell", "is_compound": True},
    {"name": "Dumbbell shoulder press", "muscle_group": "shoulders", "pattern": "push", "equipment": "dumbbell", "is_compound": True},
    {"name": "Machine shoulder press", "muscle_group": "shoulders", "pattern": "push", "equipment": "machine", "is_compound": True},
    {"name": "Pike push-up", "muscle_group": "shoulders", "pattern": "push", "equipment": "bodyweight", "is_compound": True},
    {"name": "Dumbbell lateral raise", "muscle_group": "shoulders", "pattern": "push", "equipment": "dumbbell", "is_compound": False},
    {"name": "Band face pull", "muscle_group": "shoulders", "pattern": "pull", "equipment": "bands", "is_compound": False},
    {"name": "Dumbbell front raise", "muscle_group": "shoulders", "pattern": "push", "equipment": "dumbbell", "is_compound": False},
    {"name": "Machine reverse fly", "muscle_group": "shoulders", "pattern": "pull", "equipment": "machine", "is_compound": False},
    {"name": "Barbell shrug", "muscle_group": "shoulders", "pattern": "pull", "equipment": "barbell", "is_compound": False},
    {"name": "Cable face pull (Cable)", "muscle_group": "shoulders", "pattern": "pull", "equipment": "machine", "is_compound": False},
    {"name": "Cable reverse fly (Cable)", "muscle_group": "shoulders", "pattern": "pull", "equipment": "machine", "is_compound": False},
    {"name": "Cable lateral raise (Cable)", "muscle_group": "shoulders", "pattern": "push", "equipment": "machine", "is_compound": False},
    {"name": "Cable front raise (Cable)", "muscle_group": "shoulders", "pattern": "push", "equipment": "machine", "is_compound": False},

    # --- biceps (pull) ---
    {"name": "Barbell curl", "muscle_group": "biceps", "pattern": "pull", "equipment": "barbell", "is_compound": False},
    {"name": "Dumbbell curl", "muscle_group": "biceps", "pattern": "pull", "equipment": "dumbbell", "is_compound": False},
    {"name": "Band curl", "muscle_group": "biceps", "pattern": "pull", "equipment": "bands", "is_compound": False},
    {"name": "Machine curl", "muscle_group": "biceps", "pattern": "pull", "equipment": "machine", "is_compound": False},

    # --- triceps (push) ---
    {"name": "Barbell close-grip bench press", "muscle_group": "triceps", "pattern": "push", "equipment": "barbell", "is_compound": True},
    {"name": "Dumbbell overhead extension", "muscle_group": "triceps", "pattern": "push", "equipment": "dumbbell", "is_compound": False},
    {"name": "Band pushdown", "muscle_group": "triceps", "pattern": "push", "equipment": "bands", "is_compound": False},
    {"name": "Machine triceps pushdown", "muscle_group": "triceps", "pattern": "push", "equipment": "machine", "is_compound": False},
    {"name": "Bench dip", "muscle_group": "triceps", "pattern": "push", "equipment": "bodyweight", "is_compound": True},
    {"name": "Barbell lying triceps extension", "muscle_group": "triceps", "pattern": "push", "equipment": "barbell", "is_compound": False},
    {"name": "Triceps dip", "muscle_group": "triceps", "pattern": "push", "equipment": "bodyweight", "is_compound": True},

    # --- quads (legs) ---
    {"name": "Barbell back squat", "muscle_group": "quads", "pattern": "legs", "equipment": "barbell", "is_compound": True},
    {"name": "Dumbbell goblet squat", "muscle_group": "quads", "pattern": "legs", "equipment": "dumbbell", "is_compound": True},
    {"name": "Kettlebell goblet squat", "muscle_group": "quads", "pattern": "legs", "equipment": "kettlebell", "is_compound": True},
    {"name": "Machine leg press", "muscle_group": "quads", "pattern": "legs", "equipment": "machine", "is_compound": True},
    {"name": "Bodyweight squat", "muscle_group": "quads", "pattern": "legs", "equipment": "bodyweight", "is_compound": True},
    {"name": "Band squat", "muscle_group": "quads", "pattern": "legs", "equipment": "bands", "is_compound": True},
    {"name": "Machine leg extension", "muscle_group": "quads", "pattern": "legs", "equipment": "machine", "is_compound": False},
    {"name": "Hack Squat", "muscle_group": "quads", "pattern": "legs", "equipment": "machine", "is_compound": True},
    {"name": "Barbell Bulgarian split squat", "muscle_group": "quads", "pattern": "legs", "equipment": "barbell", "is_compound": True},
    {"name": "Dumbbell Bulgarian split squat", "muscle_group": "quads", "pattern": "legs", "equipment": "dumbbell", "is_compound": True},
    {"name": "Barbell lunge", "muscle_group": "quads", "pattern": "legs", "equipment": "barbell", "is_compound": True},
    {"name": "Dumbbell lunge", "muscle_group": "quads", "pattern": "legs", "equipment": "dumbbell", "is_compound": True},

    # --- hamstrings (legs) ---
    {"name": "Barbell deadlift", "muscle_group": "hamstrings", "pattern": "legs", "equipment": "barbell", "is_compound": True},
    {"name": "Dumbbell Romanian deadlift", "muscle_group": "hamstrings", "pattern": "legs", "equipment": "dumbbell", "is_compound": True},
    {"name": "Machine leg curl", "muscle_group": "hamstrings", "pattern": "legs", "equipment": "machine", "is_compound": False},
    {"name": "Kettlebell swing", "muscle_group": "hamstrings", "pattern": "legs", "equipment": "kettlebell", "is_compound": True},
    {"name": "Bodyweight single-leg RDL", "muscle_group": "hamstrings", "pattern": "legs", "equipment": "bodyweight", "is_compound": True},
    {"name": "Barbell Romanian deadlift", "muscle_group": "hamstrings", "pattern": "legs", "equipment": "barbell", "is_compound": True},
    {"name": "Dumbbell stiff-leg deadlift", "muscle_group": "hamstrings", "pattern": "legs", "equipment": "dumbbell", "is_compound": True},
    {"name": "Barbell stiff-leg deadlift", "muscle_group": "hamstrings", "pattern": "legs", "equipment": "barbell", "is_compound": True},

    # --- glutes (legs) ---
    {"name": "Barbell hip thrust", "muscle_group": "glutes", "pattern": "legs", "equipment": "barbell", "is_compound": True},
    {"name": "Dumbbell glute bridge", "muscle_group": "glutes", "pattern": "legs", "equipment": "dumbbell", "is_compound": False},
    {"name": "Band glute bridge", "muscle_group": "glutes", "pattern": "legs", "equipment": "bands", "is_compound": False},
    {"name": "Bodyweight glute bridge", "muscle_group": "glutes", "pattern": "legs", "equipment": "bodyweight", "is_compound": False},
    {"name": "Machine hip adductor", "muscle_group": "glutes", "pattern": "legs", "equipment": "machine", "is_compound": False},
    {"name": "Machine hip abductor", "muscle_group": "glutes", "pattern": "legs", "equipment": "machine", "is_compound": False},
    {"name": "Cable kickback (Cable)", "muscle_group": "glutes", "pattern": "legs", "equipment": "machine", "is_compound": False},
    {"name": "Machine standing kickback", "muscle_group": "glutes", "pattern": "legs", "equipment": "machine", "is_compound": False},
    {"name": "Dumbbell back extension", "muscle_group": "glutes", "pattern": "legs", "equipment": "dumbbell", "is_compound": False},

    # --- calves (legs) ---
    {"name": "Machine calf raise", "muscle_group": "calves", "pattern": "legs", "equipment": "machine", "is_compound": False},
    {"name": "Dumbbell calf raise", "muscle_group": "calves", "pattern": "legs", "equipment": "dumbbell", "is_compound": False},
    {"name": "Bodyweight calf raise", "muscle_group": "calves", "pattern": "legs", "equipment": "bodyweight", "is_compound": False},

    # --- core ---
    {"name": "Plank", "muscle_group": "core", "pattern": "core", "equipment": "bodyweight", "is_compound": False},
    {"name": "Bodyweight crunch", "muscle_group": "core", "pattern": "core", "equipment": "bodyweight", "is_compound": False},
    {"name": "Band Pallof press", "muscle_group": "core", "pattern": "core", "equipment": "bands", "is_compound": False},
    {"name": "Dumbbell weighted sit-up", "muscle_group": "core", "pattern": "core", "equipment": "dumbbell", "is_compound": False},
    {"name": "Bodyweight oblique crunch", "muscle_group": "core", "pattern": "core", "equipment": "bodyweight", "is_compound": False},
    {"name": "Stability ball crunch", "muscle_group": "core", "pattern": "core", "equipment": "bodyweight", "is_compound": False},
]
