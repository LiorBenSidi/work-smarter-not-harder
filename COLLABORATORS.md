# Work Smarter, Not Harder — Team Collaboration Guide

> **Read this before writing code.** Who owns what, how the pieces connect (the contracts = the only
> fixed things), the workflow, and how to run the stack. Your detailed per-person roadmap is in `PERSON1/2/3.md`.

## Team
| Person | GitHub | Owns | Roadmap |
|---|---|---|---|
| **Shiri** | `shiriHaboob` | **AI brain** — model, `/predict`, recommendation engine, the dataset | [PERSON1.md](PERSON1.md) |
| **Lior** | `LiorBenSidi` | **Web app** — auth, profile, dashboard, history, frontend | [PERSON2.md](PERSON2.md) |
| **Elad** | `EladNa1` | **Infra + deploy + data + real-time** — compose, Mongo container + `services/db.py`, rate-limit, Azure deploy + CD, Forum real-time, stress | [PERSON3.md](PERSON3.md) |
| **Shared** | all three | **Tests** — each owns their plane's unit tests; all run in the one CI; Elad anchors integration/system/stress | — |

Roles are **containers/aspects**, not a rigid feature list — see "Freedom" below.

## How it fits together — the contracts (the ONLY fixed shared things)
These are the seams between owners. Change one → update `docs/DESIGN.md` **and tell the team** (a "sync point").
- **`web → ai`** — `POST /predict {features} -> {state, proba, recommendations}` (DESIGN §3).
- **`web → db`** — `web` calls **Elad's `services/db.py` functions** (the data API); Elad owns `db.py` + the Mongo container (collections `users / profiles / programs / analysis_history`, DESIGN §2).
- **Container boundaries** — only `web` is exposed (host 8000 → container 5000); `ai` + `db` internal.

Behind these, implement however you like.

## Freedom (and the few mandatory things)
Each owner implements their aspect **their own way** — your structure, libraries, and approach behind your
contract. The only non-negotiables are the **course requirements** (listed in each PERSON file): the 5 test
types, password hashing, only-`web`-exposed, model-baked-into-the-image, etc. **This is a roadmap, not a
step-by-step script.**

## Workflow
- Branch (`feat|fix|test|docs|chore/…`) → PR → **CI green → merge your own PR** (no peer approval — see `CONTRIBUTING.md`).
- Enable the local gate once: `sh scripts/setup-hooks.sh` + `pip install -r requirements-dev.txt`.
- **Commit regularly** — GitHub history is graded; every member commits.
- Write tests **with** your feature (you own your tests; CI runs the whole suite on every PR).

## Run it
```sh
cp .env.example .env
docker compose up --build        # 3 containers; then open http://localhost:8000/health
```
The skeleton is **runnable now** — `/health` works on all three; feature endpoints return **501** until their owner implements them.

## Sync points (when to coordinate)
1. **Kickoff** — confirm the split, run the stack, claim your PERSON file.
2. **Contract change** — anyone touching a shared contract (above) flags it in the PR + the group chat.
3. **Pre-demo** (before 16 Jul) — integrate; the MVP runs end-to-end.
4. **Pre-submit** (before 23 Aug) — freeze, full test suite, report + video.

## Plan & rubric
Phased build plan: [`docs/ROADMAP.md`](docs/ROADMAP.md). Grading rubric (80 + 10 + 10): [`docs/FEEDBACK.md`](docs/FEEDBACK.md).
