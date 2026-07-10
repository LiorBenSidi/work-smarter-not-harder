# For Shiri — the `/predict` contract (plug the model in with zero rework)

The whole web app + UI are already wired to a fixed shape. If your model returns **exactly this shape**, nothing on Lior's or Elad's side changes — it "just works." All of this is verified against the current repo code (paths cited).

## Where you write code (only these 3 spots)
1. **`ai/inference.py` → `predict_one(features)`** — replace the placeholder body with the real model. **Keep the function name, signature, and module-level location** (Elad's queue pickles it by name for the process pool — see the docstring). Load the model **once at import time** (module scope), not per call.
2. **`ai/model/train.py`** — implement training → writes `ai/model/model.pkl` (baked into the image).
3. **`ai/calories.py`** — already done for you; just **call** it from `predict_one` (see below).

Don't touch `ai/app.py`, `ai/jobqueue.py`, or anything in `web/` — they already handle routing, the queue, timeouts, and the UI.

## The response your `predict_one` MUST return
```python
{
    "state": "Ready",                 # exactly one of: "Ready" | "Moderate" | "Rest"
    "proba": {                        # per-class confidence, finite floats, ~sum to 1.0
        "Ready": 0.71,
        "Moderate": 0.22,
        "Rest": 0.07,
    },
    "recommendations": [              # list of short strings (action items); may be empty
        "Green light — hit today's planned session.",
    ],
    "calories": 2450,                 # daily kcal target (a finite number). optional but wanted for F4.
}
```
- **Remove** the `"placeholder": True` key.
- ⚠️ **The three states must be exactly `Ready` / `Moderate` / `Rest`.** The UI is styled only for those (`web/templates/index.html` → `.readiness.ready/.moderate/.rest` + the per-state proba breakdown). A different label (e.g. "Recovery-Needed") renders with no colour and needs a frontend change — so keep to these three unless you tell Lior first.
- `calories` is read at the **top level** of the response (`web/routes/checkin.py` + `dashboard.py` do `prediction.get("calories")`). Non-finite (NaN/Inf) is dropped by web, so return a real number.

## The input you receive
`features` is one dict = **the user's profile merged with today's check-in**:

**Daily check-in metrics** (`web/routes/checkin.py` → `CHECKIN_FIELDS`, always present, already validated + finite):
| key | range | type |
|---|---|---|
| `sleep_hours` | 0–24 | float |
| `resting_hr` | 30–220 | int |
| `fatigue` | 1–10 | int |
| `soreness` | 1–10 | int |
| `training_load` | 0–10 | int |

**Profile fields** (merged in; may be partial — don't assume all exist). The ones the calorie helper needs: `weight_kg`, `height_cm`, `age`, `sex` (`"male"`/`"female"`), `activity_level` (`sedentary`/`light`/`moderate`/`active`/`very_active`), `goal` (`lose`/`maintain`/`gain`).

## The calorie target — already built, just call it
`ai/calories.py` gives you (pure, tested):
```python
from calories import daily_calorie_target
kcal = daily_calorie_target(weight_kg, height_cm, age, sex, activity_level, goal)  # -> float
```
Wrap it so a missing/odd profile doesn't crash `predict_one` (a raised exception becomes a 500):
```python
try:
    kcal = daily_calorie_target(f["weight_kg"], f["height_cm"], f["age"], f["sex"],
                                f.get("activity_level", "moderate"), f.get("goal", "maintain"))
except (KeyError, TypeError, ValueError):
    kcal = None
```

## Hard rules (why zero-rework depends on them)
- **Pure & CPU-bound, no I/O** in `predict_one` (it runs in a worker process). Model load = module scope, once.
- **Never raise on bad/partial input** — return a sane default instead (a raise → HTTP 500 to the user). Missing metric → default it; unknown profile → skip calories.
- **Finite numbers only** in `proba` and `calories` (web guards and drops NaN/Inf).
- **Fast:** must return within **`AI_PREDICT_TIMEOUT_SECONDS` = 30s** (a Random Forest `.predict` is milliseconds — no worry).
- **Feature order:** build the model's input vector from the keys above **in a fixed order you control** inside `predict_one` (map the dict → your array), so training and inference agree.

## Training (`ai/model/train.py`) — the plan already in the repo
1. Load **PMData** (`wellness.csv` + `srpe.csv`), merge per participant **by date**.
2. **Bin readiness 0–10 into the 3 classes** (`Ready` / `Moderate` / `Rest`).
3. Train a **Random Forest** on the same feature keys web sends (`sleep_hours`, `resting_hr`, `fatigue`, `soreness`, `training_load` [+ any profile features you use]).
4. `joblib.dump(model, "ai/model/model.pkl")`.
5. **Pin `scikit-learn`** in `ai/requirements.txt` to the exact version you trained with (so the pickle loads inside the container).
6. **Keep the raw dataset OUT of the repo** — bake only `model.pkl` into the image (the `ai/Dockerfile` copies `model/`).

## How to know it worked (no rework needed)
- Run the ai tests: they exercise the `/predict` contract and the queue. If `predict_one` returns the shape above, they stay green.
- End-to-end: `docker compose up --build`, register + do a check-in in the app — the readiness orb should show a **real** state/probabilities (not always "Moderate") and a calorie number.

Full design contract: `docs/DESIGN.md`. Model notes/decisions: `ai/README.md`.
