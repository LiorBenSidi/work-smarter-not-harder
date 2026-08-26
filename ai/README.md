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

## Feature selection

The initial proposal's candidate feature list also included resting heart rate, HR drift from
baseline, and body-weight trend. These were evaluated during development, and the final
four-feature set — `sleep_hours`, `fatigue`, `soreness`, `training_load` — was selected based on
that evaluation. The comparison itself wasn't saved as a notebook or reproducible run; only the
final chosen set is reflected in the committed code. The proposal explicitly left this list open
pending real experimentation with the data, and this is the outcome of that process.

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

### Performance and calibration

The model is trained and shipped as described above. Its measured performance (overall accuracy
~0.55, Ready-class precision/recall ~0.31/0.30) and probability calibration were not pushed
further — the proposal never committed to a specific accuracy or calibration target, and the team
chose to treat the current model as final rather than continue tuning it.

The model uses sleep hours, fatigue, soreness, and training load as input features. User inputs are converted when needed to match the scales used during model training.

The trained model is stored in `ai/model/model.pkl`, and the training results are stored in `ai/model/training_report.json`.

The model is baked into the Docker image and loaded locally at runtime. No model download or training occurs while the service is running.

## Exercise catalog

The workout generator (`ai/workout_plan.py`, `ai/exercise_catalog.py`) draws from **99** hand-curated
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
| Chest | 15 |
| Shoulders | 13 |
| Quads | 12 |
| Back | 11 |
| Biceps | 10 |
| Glutes | 9 |
| Hamstrings | 8 |
| Triceps | 8 |
| Core | 7 |
| Calves | 6 |
| **Total** | **99** |

### How much of the catalog the generator actually reaches

`generate_workout_days`'s real reach was measured exhaustively rather than estimated: across every
one of the 127 possible non-empty equipment subsets, all 3 resolved splits, and every
`training_frequency` from 1 to 14 (5,334 calls total), **50 of the 99 catalog entries are ever
selected** — the other 49 are structurally unreachable under the generator as it exists today (the
picker prefers the same exercise for a given muscle-group/pattern/equipment/day-type slot and never
rotates, so isolation variants and secondary-equipment alternates for an already-covered slot are
never chosen).

That 50/99 split does not reduce the risk of auditing a swap, and is not read as a reason to trim the
catalog to just the reachable half: `is_compound`/`is_isometric` still need the same manual judgment
per entry regardless of which half happens to be live right now; a dataset swap's license risk is
independent of exercise count; and the unreached entries are not safe to drop — they exist for
equipment-degradation coverage that different athletes' equipment does reach, and a future change to
the picker (adding rotation for weekly variety, for instance) would need them.

**Known, accepted gap: biceps has zero bodyweight-equipment exercises in the catalog** — a
bodyweight-only athlete gets no biceps exercise on any day. Not something being built around right
now: a self-resistance/isometric bodyweight curl was considered and rejected as too non-standard for
this catalog, and a pull-up-bar exercise (e.g. Chin-up) was also considered and rejected since it
requires equipment, contradicting the bodyweight-only case it would exist to address.

## Recommendations and calories

After predicting the readiness state, the recommendation engine uses the current recovery metrics and available user information to generate actionable recommendations.

The recommendation engine can use:

- readiness state and current recovery metrics
- the user's goal
- optional recent history
- optional weekly performed training volume, per muscle group

When history is available, the engine can detect repeated low-readiness states and trends such as declining sleep or increasing fatigue.

When weekly performed-volume information is available, it can identify simple training-volume imbalances between muscle groups.

The engine does not invent missing measurements. If optional information is unavailable or invalid, it uses only the valid information that was actually provided.

### Why the balance analysis reads performed volume, not the prescribed plan

The muscle-group balance analysis (`_program_recommendations`) is fed `features["performed"]` —
what the athlete actually logged — not the plan the workout generator itself prescribed. This is a
deliberate choice, made after measuring the alternative, not an oversight: feeding the analysis its
own generator's output was tried, and running it against every split/frequency/equipment
combination `generate_workout_days` can produce showed the prescribed plan is balanced by
construction — volume always lands inside the analysis's own thresholds (6–20 sets per muscle
group, chest:back ratio 0.67–1.5), so it could never actually fire. A balance check against a plan
the same engine just wrote would also be circular even if it did fire. The analysis itself was
always correct; it just never had a real input. Real signal needs what the athlete actually did,
which is why `features["performed"]` — a new, currently-proposed addition to the `/predict` request
contract — carries logged volume instead. See `docs/DESIGN.md` §3 for the proposed shape and
`docs/PERFORMED_VOLUME_SPEC.md` for the full collection/aggregation proposal (both pending review,
not yet sent to the team).

Daily calorie targets are calculated using the Mifflin-St Jeor equation when enough valid profile information is available. Invalid or incomplete profile data does not cause prediction to fail; the calorie field is simply omitted.

## Validation and testing

The model is validated by participant rather than by randomly splitting individual rows. This provides a more realistic test of generalization to users who were not seen during training.

The AI tests cover:

- readiness binning
- model inference and probabilities
- recommendation generation
- partial and invalid inputs
- trend analysis
- performed-volume balance
- calorie calculation
- queue and API compatibility

The recommendation-engine test suite currently passes all 19 tests. The full AI prediction path was also tested successfully both locally and inside the Docker container.

## Performance and parallel programming

The measured average `predict_one` latency over 1,000 predictions was approximately **33.6 ms**.

Inside the Docker container, total process memory after loading the inference code and trained model was approximately **159.24 MB**. The estimated memory increase from importing the inference stack and loading the model was approximately **151.11 MB**.

Single-row prediction is not artificially parallelized. CPU-bound prediction requests are handled through the bounded process pool in front of `predict_one`, while NumPy and Pandas vectorized operations are used where appropriate in the data pipeline.

## Reproducibility

Training produces:

- `ai/model/model.pkl`
- `ai/model/training_report.json`

At runtime, the service only loads the trained model and does not retrain it. Model dependencies are pinned in `ai/requirements.txt`, and the raw dataset remains outside the repository.