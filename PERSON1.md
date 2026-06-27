# PERSON 1 — Shiri — the AI brain (model · recommendations · data)

> Your **area + the mandatory course items + a roadmap** — *not* a step-by-step script. How you build behind the
> contract is yours. Your container: `ai/` (+ the dataset/pipeline). Notes are started in [`ai/README.md`](ai/README.md).

## Why you
It's your idea and you know the domain best — so the **coaching brain** is yours: what a readiness state means,
which fitness signals matter, and what the app should recommend. (Elad's strong at ML too and is a resource if you want one; Lior can help wire the glue.)

## Your contract (fixed — the rest of the app depends on it)
`POST /predict {features: {...}} -> {state, proba, recommendations}` (docs/DESIGN.md §3). Internal-only container.
Changing the shape is a **sync point** — update DESIGN + tell the team.

## Mandatory (course — graded)
- **Local model, baked into the image** (`joblib` → `COPY` → load; no runtime download/train). **Pin scikit-learn** to your training version.
- **Scaling:** the model serves behind gunicorn workers + `ai` replicas (Elad runs the replicas); reach for `multiprocessing` only for a *measured* heavy step (training/batch).
- **Fault tolerance** — keep `/predict` well-behaved; your container can fail without crashing the app (web degrades).
- **Tests run anywhere** (no machine paths) — unit (predict + binning) + the recommendation logic.

## Roadmap (build these — your way)
- [ ] **Data** — load PMData (or another set), merge `wellness` + `srpe` by date into one table.
- [ ] **Classes + features** — bin `readiness` 0–10 into classes (3-class is the natural fit); pick the feature set (a domain call).
- [ ] **Train** → `model/model.pkl`; bake it into the image; **validate** it (don't ship an unmeasured model).
- [ ] **`POST /predict`** — replace the placeholder → real `state` + `proba`.
- [ ] **Recommendation engine** — state + goals + program + recovery → **workout (F5)** · **action-plan + program-balance (F6+F7)** · trend analysis over history. *(F4 calorie is already built + tested in [`ai/calories.py`](ai/calories.py) — a head start to fold in.)*
- [ ] **Augmentation** if labeled data is thin — bootstrap whole rows / SMOTE (never independent marginals — see `ai/README.md`).
- [ ] **Forum slice** — the cold-seed *generator* (realistic fitness posts/threads).

## You own the decisions
Dataset, model, binning, features, augmentation, and the coaching rules — all yours. Record them in [`ai/README.md`](ai/README.md).
