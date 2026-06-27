# Design — Work Smarter, Not Harder

Living technical design. **Spec sources:** the submitted [`PROPOSAL.md`](PROPOSAL.md) (graded 100/100 — the contract)
+ the revised [`PROPOSAL-v2.md`](PROPOSAL-v2.md) (current intent). **Driving rubric:** [`FEEDBACK.md`](FEEDBACK.md).
Items marked *proposed* are confirmed at the kickoff; open decisions are at the bottom; reference the PR that changes a decision.

## 1. Architecture — 3 containers (only `web` exposed)
- **web** — Flask: frontend + auth (werkzeug hashing) + API. Host **8000** → container 5000 (never publish 5000 — macOS AirPlay). The only user-facing container.
- **db** — MongoDB. Internal only; named volume for persistence; healthcheck + `depends_on`.
- **ai** — model inference + recommendation generation. Internal only (`expose`, no host port).

```
User → web ──┬──► ai   (POST /predict, internal)
             └──► db   (mongodb://db:27017, internal)
```

## 2. Data model (MongoDB — PROPOSAL §9)
- `users` — { username, password_hash }
- `profiles` — { user_id, age, gender, height, weight, goal, training_frequency }
- `programs` — { workout programs / exercise catalog }
- `analysis_history` — { user_id, assessment, recommendations, calories, timestamp }

## 3. API contracts
| Endpoint | Method | Container | Notes |
|---|---|---|---|
| `/register` `/login` `/logout` | POST | web | werkzeug hashing; session/token; auth-gate decorator |
| `/profile` | GET/POST | web | reads/writes `profiles`; validate input (NoSQL-injection guard) |
| `/predict` | POST | ai (internal) | state assessment + recommendations |

**`web → ai` `POST /predict`** (internal): request `{ features: { sleep_hours, resting_hr, hr_change, fatigue, soreness, weekly_freq, training_load, calorie_balance, bodyweight_trend } }` → response `{ state: <category>, proba: {…}, recommendations: {…} }`. *(Feature set + category list are a candidate set — finalized during data exploration.)*

## 4. AI decision engine (the heart)
One pipeline, two capabilities:
1. **State assessment** — a supervised classifier (**Random Forest** chosen: ML-course-taught, local, fast, explainable; **swappable** behind the `/predict` contract) → a small set of training-state categories (exact set TBD).
2. **Recommendation generation** — combines the assessment + goals + program + recovery → action plan / workout / program adjustments / calories.

- **Baked into the `ai` image** (`joblib.dump` → `COPY` → `joblib.load`; **pin sklearn** so the pickle loads). Never train/download at runtime.
- **CPU-bound inference → `multiprocessing`** (the parallel/scaling story; `ai` replicas for multi-machine).
- Trained on wellness + program-catalog data; any synthetic augmentation (bootstrapping / class-balancing) documented.

## 5. Security & fault tolerance
- Hash passwords (werkzeug); auth-gate protected endpoints; rate-limit; validate input; defend NoSQL injection; only `web` exposed.
- `ai` down → `web` returns "assessment unavailable" (no crash); `db` down → reduced functionality; wearable data missing → manual entry.

## 6. Testing (the requirement persists — kept out of the spec doc per Noam, tracked here)
All **5 course test types** live in `tests/{Unit,Integration,System,Stress,Security}_Tests/` + a **feature×test matrix** maintained in the repo/report (not in the proposal, per Noam's "this doc is no place for tests"). `TESTING`/`debug` env flags; tests run on any machine (no local paths). CI runs them on every commit; a 0-test run fails.

## 7. Decisions (mini-ADRs)
- **3 containers, only `web` exposed** — course rule; only `web` gets host ports.
- **Local RF, baked into the image** — no runtime train/download; pin sklearn; RF swappable behind `/predict`.
- **F6 + F7 merged** → one "Program Balance & Action Plan" pipeline (analysis feeds prioritization; two capabilities from the user's view). ⚠️ **Pending Noam's email OK** — merging a feature needs his sign-off; the submitted **9-feature** scope is the graded contract until he confirms.
- **`multiprocessing` for inference** — the parallel/scaling section.

## 8. Open / to confirm
- **F6+F7 merge** — awaiting Noam's reply.
- **Smartwatch import** — stretch; awaiting Noam (Samsung has no web API → likely a real export-file parse).
- **Exact training-state categories + final feature set** — during data exploration.
- **Deploy ordering** (Azure right after MVP vs after the 80) — team decision.
- **Forum real-time layer** (SSE vs Flask-SocketIO) — at Phase 3.
