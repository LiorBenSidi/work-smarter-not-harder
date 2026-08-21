# AI Decision Engine

The `ai` service predicts the user's current readiness state and returns personalized training and recovery recommendations.

The main prediction contract is:

`POST /predict {"features": {...}} -> {"state": ..., "proba": {...}, "recommendations": [...]}`

When enough valid profile information is available, the response also includes a daily calorie target.

## Dataset and preprocessing

The model is trained on the PMData sports-logging dataset, available on Kaggle:

https://www.kaggle.com/datasets/vlbthambawita/pmdata-a-sports-logging-dataset

The dataset contains wellness and training information from 16 participants over approximately five months.

The training dataset is built by merging daily wellness data with sRPE training data by participant and date. The model uses four features:

- `sleep_hours`
- `fatigue`
- `soreness`
- `training_load`

The PMData readiness score is converted into three classes: `Rest`, `Moderate`, and `Ready`.

Participant IDs are preserved during preprocessing so validation can be grouped by participant. This avoids placing records from the same person in both training and validation data.

The raw dataset is not committed to the repository.

## Model

The final model is a Random Forest classifier. It was chosen because the dataset is relatively small and tabular, and because the relationships between recovery metrics and readiness may be nonlinear.

Several Random Forest configurations were compared during training. The selected candidate is `leaf6_depth_none__balanced`, and the current `Ready` probability threshold is `0.60`.

Class imbalance is handled using `class_weight="balanced"`, which gives more importance during training to classes with fewer examples.

No synthetic augmentation (bootstrapping whole rows, SMOTE, or similar) is used in the shipped
model. This is a deliberate, evidence-based choice, not an oversight: bootstrap augmentation was
evaluated against `class_weight="balanced"` under the same participant-grouped cross-validation
used to select the model, bootstrapping only each training fold so no synthesized row could leak
into a validation fold. It performed worse — overall Macro-F1 dropped from `0.4646` to `0.4427`,
and Ready-class F1 dropped from `0.2802` to `0.2222` — so the final model keeps
`class_weight="balanced"` instead.

The model uses sleep hours, fatigue, soreness, and training load as input features. User inputs are converted when needed to match the scales used during model training.

The trained model is stored in `ai/model/model.pkl`, and the training results are stored in `ai/model/training_report.json`.

The model is baked into the Docker image and loaded locally at runtime. No model download or training occurs while the service is running.

## Exercise catalog

The workout generator (`ai/workout_plan.py`, `ai/exercise_catalog.py`) draws from **98** hand-curated
exercise entries, not a public dataset. This is a deliberate choice, evaluated against the
alternative rather than assumed.

Four public exercise/workout datasets were researched as possible replacements or supplements:
free-exercise-db (800+ entries, Unlicense/public domain), wger (845+ entries, app AGPL-3+ / exercise
data CC-BY-SA 3.0), exercemus/exercises (MIT, curated from the above two plus wger, ships a
pre-built muscle-group map), and exercises-dataset (1,324 entries, MIT). None uses the same 10-group
muscle taxonomy this catalog does, so each would need a manual remap, and none of the four carries
`is_compound`/`is_isometric` fields at all — both are hand-judged per entry in the current catalog
(Plank as the sole isometric, for example, was an individual decision, not something derivable
mechanically from any of these sources).

**Decision: keep the current hand-curated catalog, not swap.** Auditing hundreds of imported entries
for correctness — `is_compound`/`is_isometric` especially — carries real risk of silent errors, and
none of the four datasets researched combines a clean license, this catalog's exact muscle-group
taxonomy, and those two fields. The provenance is already disclosed in the catalog's own module
docstring (`ai/exercise_catalog.py:1-6`).

### Coverage per muscle group

Every one of the 10 muscle groups has at least 6 exercises (measured directly from
`EXERCISE_CATALOG`, not estimated):

| Group | Exercises |
|---|---:|
| Chest | 14 |
| Shoulders | 13 |
| Quads | 12 |
| Back | 11 |
| Biceps | 10 |
| Glutes | 9 |
| Hamstrings | 8 |
| Triceps | 8 |
| Core | 7 |
| Calves | 6 |
| **Total** | **98** |

### How much of the catalog the generator actually reaches

`generate_workout_days`'s real reach was measured exhaustively rather than estimated: across every
one of the 127 possible non-empty equipment subsets, all 3 resolved splits, and every
`training_frequency` from 1 to 14 (5,334 calls total), **49 of the 98 catalog entries are ever
selected** — the other 49 are structurally unreachable under the generator as it exists today (the
picker prefers the same exercise for a given muscle-group/pattern/equipment/day-type slot and never
rotates, so isolation variants and secondary-equipment alternates for an already-covered slot are
never chosen).

That 49/98 split does not reduce the risk of auditing a swap, and is not read as a reason to trim the
catalog to just the reachable half: `is_compound`/`is_isometric` still need the same manual judgment
per entry regardless of which half happens to be live right now; a dataset swap's license risk is
independent of exercise count; and the unreached entries are not safe to drop — they exist for
equipment-degradation coverage that different athletes' equipment does reach, and a future change to
the picker (adding rotation for weekly variety, for instance) would need them.

## Recommendations and calories

After predicting the readiness state, the recommendation engine uses the current recovery metrics and available user information to generate actionable recommendations.

The recommendation engine can use:

- readiness state and current recovery metrics
- the user's goal
- optional recent history
- optional weekly program information

When history is available, the engine can detect repeated low-readiness states and trends such as declining sleep or increasing fatigue.

When weekly program information is available, it can identify simple training-volume imbalances between muscle groups.

The engine does not invent missing measurements. If optional information is unavailable or invalid, it uses only the valid information that was actually provided.

Daily calorie targets are calculated using the Mifflin-St Jeor equation when enough valid profile information is available. Invalid or incomplete profile data does not cause prediction to fail; the calorie field is simply omitted.

## Validation and testing

The model is validated by participant rather than by randomly splitting individual rows. This provides a more realistic test of generalization to users who were not seen during training.

The AI tests cover:

- readiness binning
- model inference and probabilities
- recommendation generation
- partial and invalid inputs
- trend analysis
- program balance
- calorie calculation
- queue and API compatibility

The recommendation-engine test suite currently passes all 14 tests. The full AI prediction path was also tested successfully both locally and inside the Docker container.

## Performance and parallel programming

The measured average `predict_one` latency over 1,000 predictions was approximately **33.6 ms**.

Inside the Docker container, total process memory after loading the inference code and trained model was approximately **159.24 MB**. The estimated memory increase from importing the inference stack and loading the model was approximately **151.11 MB**.

Single-row prediction is not artificially parallelized. CPU-bound prediction requests are handled through the bounded process pool in front of `predict_one`, while NumPy and Pandas vectorized operations are used where appropriate in the data pipeline.

## Reproducibility

Training produces:

- `ai/model/model.pkl`
- `ai/model/training_report.json`

At runtime, the service only loads the trained model and does not retrain it. Model dependencies are pinned in `ai/requirements.txt`, and the raw dataset remains outside the repository.