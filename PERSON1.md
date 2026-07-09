# PERSON 1 — Shiri — the AI (model · recommendations · data)

> Your area, the mandatory course items, and a roadmap. Behind the contract, how you build is your call.
> Your container: `ai/` (+ the dataset/pipeline). Notes started in [`ai/README.md`](ai/README.md).

## Start now — unblocked on day 1
The `ai/` container is standalone (no dependency on `web` or `db`), so you can build and test the model and
`/predict` in isolation via the Flask test client — in parallel with everyone else, from the first commit.

**Running the app · live email (optional):** the stack runs fully in **mock mode with zero secrets** (codes show
on screen) — all you need for normal work. To send *real* email locally, get the `.env` from **Lior** over a
private channel (AirDrop / DM) → drop it in your repo root → `docker compose up --build`. It's gitignored —
never commit it. Full guide: [`SECRETS.md`](SECRETS.md).

## Your contract (fixed — the rest of the app depends on it)
`POST /predict {features: {...}} -> {state, proba, recommendations}` (docs/DESIGN.md §3). Internal-only container.
Changing the shape is a **sync point** — update DESIGN + tell the team.

## Mandatory (course — graded)
- **Local model, baked into the image** (`joblib` → `COPY` → load; no runtime download/train). **Pin scikit-learn**.
- **Parallel programming (L7):** include a *measured* `multiprocessing` path for a CPU-bound batch (recommendation search / batch scoring / similarity) + NumPy vectorization in the feature pipeline — not the single-row predict. Serve behind gunicorn workers + `ai` replicas.
- **Fault tolerance:** keep `/predict` well-behaved so a failure degrades (web handles it), never crashes the app.
- **Tests run on any machine** (no local paths) — unit (predict + binning) + the recommendation logic. A `TESTING` flag can expose internals for testing.

## Roadmap (build these — your way)
- [ ] **Data** — load PMData (or another set), merge `wellness` + `srpe` by date into one table.
- [ ] **Classes + features** — bin `readiness` 0–10 into classes (3-class is a natural fit); pick the feature set.
- [ ] **Train** → `model/model.pkl`; bake into the image; **validate** it.
- [ ] **`POST /predict`** — replace the placeholder → real `state` + `proba`.
- [ ] **Measure the model's predict-time + peak RAM per process** — one `predict_one` call's latency, and the loaded model's memory. These two numbers size production settings behind the `/predict` contract: the queue timeout (`AI_PREDICT_TIMEOUT_SECONDS`, currently 30 s) and the worker-pool count (`AI_QUEUE_WORKERS`, currently 4 — each pool process loads its own copy of the model, and the VM is a Standard E4ads v5 with 4 vCPU / 32 GiB, so RAM is unlikely to bind unless the model is very large). Just report the two numbers; the timeout/pool config itself isn't yours to edit.
- [ ] **Recommendation engine** — state + goals + program + recovery → workout (F5) · action-plan + program-balance (F6+F7) · trend analysis over history. *(F4 calorie is implemented in [`ai/calories.py`](ai/calories.py).)*
- [ ] **Augmentation** if labeled data is thin — bootstrap whole rows / SMOTE (see `ai/README.md`).
- [ ] **Forum:** the cold-seed content generator.

## You own the decisions
Dataset, model, binning, features, augmentation, the recommendation rules — recorded in [`ai/README.md`](ai/README.md).
