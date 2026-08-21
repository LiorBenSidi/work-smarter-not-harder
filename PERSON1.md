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
`POST /predict {features: {...}} -> {state, proba, recommendations, plan}` (docs/DESIGN.md §3). Internal-only container.
Changing the shape is a **sync point** — update DESIGN + tell the team.

## Mandatory (course — graded)
- **Local model, baked into the image** (`joblib` → `COPY` → load; no runtime download/train). **Pin scikit-learn**.
- **Fault tolerance:** keep `/predict` well-behaved so a failure degrades (web handles it), never crashes the app.
- **Tests run on any machine** (no local paths) — unit (predict + binning) + the recommendation logic. A `TESTING` flag can expose internals for testing.

## Roadmap (build these — your way)
- [x] **Data** — load PMData (or another set), merge `wellness` + `srpe` by date into one table. Done: `scripts/build_training_dataset.py`, 1729 rows / 16 participants.
- [x] **Classes + features** — bin `readiness` 0–10 into classes (3-class is a natural fit); pick the feature set. Done: Rest/Moderate/Ready, `sleep_hours`/`fatigue`/`soreness`/`training_load`.
- [x] **Train** → `model/model.pkl`; bake into the image; **validate** it. Done: participant-grouped 5-fold CV, baked into `ai/Dockerfile`.
- [x] **`POST /predict`** — replace the placeholder → real `state` + `proba`. Done: `ai/inference.py` calls the real Random Forest.
- [x] **Measure the model's predict-time + peak RAM per process** — one `predict_one` call's latency, and the loaded model's memory. These two numbers size production settings behind the `/predict` contract: the queue timeout (`AI_PREDICT_TIMEOUT_SECONDS`, currently 30 s) and the worker-pool count (`AI_QUEUE_WORKERS`, currently 4 — each pool process loads its own copy of the model, and the VM is a Standard E4ads v5 with 4 vCPU / 32 GiB, so RAM is unlikely to bind unless the model is very large). Just report the two numbers; the timeout/pool config itself isn't yours to edit. Done: ~33.6 ms mean latency, ~159 MB RSS — `docs/SCALING_REPORT.md`, `ai/README.md`.
- [ ] **Recommendation engine** — state + goals + program + recovery → workout (F5) · action-plan + program-balance (F6+F7) · trend analysis over history. *(F4 calorie is implemented in [`ai/calories.py`](ai/calories.py).)* **Status: F5 done (`ai/workout_plan.py`, wired into `/predict`) · F7 done (`generate_recommendations`) · trend analysis done and actually used (`_history_recommendations`) · F6/#276 P7 fix ready but not yet merged: `_program_recommendations` now reads `features["performed"]` instead of prescribed `program` data in PR #529 (open, pending review). Leaving unchecked until that PR actually merges.**
- [x] **Augmentation** if labeled data is thin — bootstrap whole rows / SMOTE (see `ai/README.md`). **Status: evaluated and rejected with evidence. Bootstrap augmentation was tested against `class_weight="balanced"` under the same participant-grouped CV used to select the model and performed worse (Macro-F1 0.4646→0.4427, Ready-F1 0.2802→0.2222); `class_weight="balanced"` was kept. Documented in `ai/README.md`.**
- [x] **Forum:** the cold-seed content generator. **Status: done — built entirely by Lior (`db/seed.py`, `seed.sh`), not `ai/` work. Verified by actually running the script against a fresh database: 5 users, 5 posts, 6 comments, real likes, idempotent re-run confirmed. Full git history search (all branches, all commits) found zero abandoned or partial AI-side content-generator work — nothing was ever started here.**
- [x] **Exercise catalog provenance** — decided to keep the hand-curated catalog rather than swap to a public dataset (four datasets researched; none combined a clean license, our exact muscle-group taxonomy, and the `is_compound`/`is_isometric` fields the engine depends on). **Status: closed in #528. Catalog also expanded 87→98 entries so every muscle group has 5+ exercises (up from as few as 3–4). Full reasoning in `ai/README.md`.**

## You own the decisions
Dataset, model, binning, features, augmentation, the recommendation rules — recorded in [`ai/README.md`](ai/README.md).
