# `ai/` — AI decision engine (internal container)

The **AI owner owns everything in here.** The only fixed thing is the **contract** (`POST /predict`, defined in
[`../docs/DESIGN.md`](../docs/DESIGN.md)); behind it, the **dataset, model, class binning, feature engineering, and
augmentation are the owner's call** — swap any of them freely as long as `/predict` keeps its shape.

## Contract (fixed — what the rest of the system depends on)
`POST /predict` (internal): `{ features: {…} }` → `{ state: <category>, proba: {…}, recommendations: {…} }`.
Course/architecture constraints (these come with the project, not negotiable per owner): internal-only container;
the trained model is **baked into the image** (`joblib` → `COPY` → load; **pin sklearn**); CPU-bound inference uses
**`multiprocessing`** (the parallel/scaling story).

## Starting dataset — PMData (Simula)
**Current choice; the owner may swap it.** A sports-logging dataset — **16 participants, ~5 months**, **Fitbit
Versa 2 + PMSys + Google Forms** ([Simula](https://datasets.simula.no/pmdata/) ·
[Kaggle](https://www.kaggle.com/datasets/vlbthambawita/pmdata-a-sports-logging-dataset)). It matches our candidate
feature set almost 1:1 and — crucially — has a **real target label** (verified via the dataset description):
- `wellness.csv` — date/time, **fatigue, mood, readiness, sleep duration (hrs), sleep quality, soreness (+ area), stress**.
- `srpe.csv` — session end-time, activity type, **RPE**, **duration (min)** → training load **sRPE = RPE × duration**.
- **`readiness` (0–10)** is the label (0 = not ready at all, 10 = ready for anything).
- **License/data handling:** confirm the Simula terms before redistributing; **don't commit the raw data** (load it at train time; bake only the trained model into the image).

## Open decisions (the AI owner's — recorded as input, not locked)
- **Bin the continuous label → classes.** `readiness` is 0–10; our classes are discrete. A **3-class** split (e.g. 0–4 / 5–7 / 8–10) is the natural fit and eases class balance — the concrete version of PROPOSAL-v2's "number of classes is flexible."
- **"Injury Risk" has no PMData label.** Either **drop it** (→ 3 classes) or keep it **rule-based** (not ML). Dropping is simpler.
- **Preprocessing.** Merge `wellness.csv` + `srpe.csv` per participant **by date** into one table (one script).
- **Augmentation — do it right** (16 people → hundreds–thousands of person-days; small): **bootstrap whole rows** (resample full day-records — preserves the joint distribution); **SMOTE** along same-class neighbours for a sparse class; if parametric, a **dependence-preserving** model (Gaussian copula / multivariate). **Never sample each feature from its own marginal independently** — that destroys the correlations `readiness` depends on.

## Backups (if PMData proves insufficient)
- *Sleep Health and Lifestyle* — clean & tabular (sleep/stress/HR), but **no readiness label** and not athlete-specific → feature-donor only, can't train the classifier alone.
- Other "athlete recovery" tabular sets — open and check columns. **Avoid AI-synthesized sets** (e.g. "Pre/Post-Exercise Heart Rate" is simulated and has no readiness label).

## Tests (the owner writes these; CI runs the whole suite)
- Unit: `/predict` returns a valid class for a known input; the binning function maps boundary values (0, 4, 5, 7, 8, 10) to the right class.
- Integration: `web → ai` roundtrip. Plus the recommendation logic.
- (The 5-type feature×test matrix is tracked in `docs/DESIGN.md`.)
