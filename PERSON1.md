# PERSON 1 — Lior — the AI

> Your **area + mandatory course items + a roadmap**. *Not* a step-by-step script — how you build behind
> the contract is yours. Your container: `ai/` (+ the data pipeline). Your notes are started in [`ai/README.md`](ai/README.md).

## Your contract (fixed — the rest of the app depends on it)
`POST /predict {features: {...}} -> {state, proba, recommendations}` (docs/DESIGN.md §3). Internal-only container.
Changing the shape is a **sync point** — update DESIGN + tell the team.

## Mandatory (course — graded)
- **Local model, baked into the image** (`joblib` → `COPY` → load; no runtime download/train). **Pin scikit-learn** to your training version so the pickle loads.
- **CPU-bound inference → parallelism** (gunicorn workers and/or a `multiprocessing` pool) — this *is* the project's "parallel programming / scaling" section.
- **Fault tolerance** — your container may fail without crashing the app (web degrades). Keep `/predict` well-behaved.
- **Tests** in the 5-type tree for your code (unit: predict + the binning function; integration: `web → ai`).

## Roadmap (build these — your way)
- [ ] **Data** — load PMData (or another set — your call), merge `wellness` + `srpe` by date into one table.
- [ ] **Classes + features** — bin `readiness` 0–10 into classes (3-class is the natural fit); finalize the feature set.
- [ ] **Train** the model → `model/model.pkl`; bake it into the image.
- [ ] **`POST /predict`** — replace the stub → `state` + `proba`.
- [ ] **Recommendation engine** — state + goals + program + recovery → action plan / workout / calories / program-balance.
- [ ] **Augmentation** if needed — bootstrap whole rows / SMOTE (never independent marginals — see `ai/README.md`).

## You own the decisions
Dataset, model, binning, feature engineering, augmentation — all yours. Record the choices in [`ai/README.md`](ai/README.md).
