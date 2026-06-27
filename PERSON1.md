# PERSON 1 — Shiri — the AI (model · recommendations · data)

> Your area, the mandatory course items, and a roadmap. Behind the contract, how you build is your call.
> Your container: `ai/` (+ the dataset/pipeline). Notes started in [`ai/README.md`](ai/README.md).

## Start now — unblocked on day 1
The `ai/` container is standalone (no dependency on `web` or `db`), so you can build and test the model and
`/predict` in isolation via the Flask test client — in parallel with everyone else, from the first commit.

## Your contract (fixed — the rest of the app depends on it)
`POST /predict {features: {...}} -> {state, proba, recommendations}` (docs/DESIGN.md §3). Internal-only container.
Changing the shape is a **sync point** — update DESIGN + tell the team.

## Mandatory (course — graded)
- **Local model, baked into the image** (`joblib` → `COPY` → load; no runtime download/train). **Pin scikit-learn**.
- **Scaling:** serve behind gunicorn workers + `ai` replicas; reach for `multiprocessing` only for a *measured* heavy step (training/batch).
- **Fault tolerance:** keep `/predict` well-behaved so a failure degrades (web handles it), never crashes the app.
- **Tests run on any machine** (no local paths) — unit (predict + binning) + the recommendation logic. A `TESTING` flag can expose internals for testing.

## Roadmap (build these — your way)
- [ ] **Data** — load PMData (or another set), merge `wellness` + `srpe` by date into one table.
- [ ] **Classes + features** — bin `readiness` 0–10 into classes (3-class is a natural fit); pick the feature set.
- [ ] **Train** → `model/model.pkl`; bake into the image; **validate** it.
- [ ] **`POST /predict`** — replace the placeholder → real `state` + `proba`.
- [ ] **Recommendation engine** — state + goals + program + recovery → workout (F5) · action-plan + program-balance (F6+F7) · trend analysis over history. *(F4 calorie is implemented in [`ai/calories.py`](ai/calories.py).)*
- [ ] **Augmentation** if labeled data is thin — bootstrap whole rows / SMOTE (see `ai/README.md`).
- [ ] **Forum:** the cold-seed content generator.

## You own the decisions
Dataset, model, binning, features, augmentation, the recommendation rules — recorded in [`ai/README.md`](ai/README.md).
