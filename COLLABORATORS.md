# Work Smarter, Not Harder — Team Collaboration Guide

> **Read this before writing code.** Who owns what, how the pieces connect (the contracts = the only
> fixed things), the workflow, and how to run the stack. Your detailed per-person roadmap is in `PERSON1/2/3.md`.

## Team
| Person | GitHub | Owns | Roadmap |
|---|---|---|---|
| **Shiri** | `shiriHaboob` | **AI brain** — model, `/predict`, recommendation engine, the dataset, the Forum cold-seed generator | [PERSON1.md](PERSON1.md) |
| **Lior** | `LiorBenSidi` | **Web app + observability + data/container/CI plumbing** — the Flask **backend** (API · auth/sessions · validation · orchestration of ai+db) + the frontend + the **data layer & Mongo internals** (`services/db.py` thin CRUD, indexes, `$jsonSchema` validators, env-gated auth wiring, `db/seed.py`) + **Week-9 logging/observability** + the **`web`/`ai` container build & compose fault-tolerance** + the **CI gate** (the banked +5 of CI/CD) | [PERSON2.md](PERSON2.md) |
| **Elad** | `EladNa1` | **Deploy + real-time + prod ops** — **Azure deploy** (the deploy +5 of CI/CD) + the test-runner service, **operating Mongo in prod** (least-privilege app user, backups / retention), rate-limit (flask-limiter), the **Forum real-time layer** (notifications / DM / media) + stress / cross-container tests | [PERSON3.md](PERSON3.md) |
| **Shared** | all three | **Tests** — each owns their plane's unit tests; all run in the one CI; Elad anchors integration/system/stress | — |

Roles are **containers/aspects**, not a rigid feature list — see "Freedom" below.

## How it fits together — the contracts (the ONLY fixed shared things)
These are the seams between owners. Change one → update `docs/DESIGN.md` **and tell the team** (a "sync point").
- **`web → ai`** — `POST /predict {features} -> {state, proba, recommendations}` (DESIGN §3).
- **`web → db`** — `web` calls the **`services/db.py` functions** (the data API). The **thin core CRUD** (users/profiles/history/forum) is **Lior's**; the **Mongo container** + schema/indexes (collections `users / profiles / analysis_history / forum_posts`, DESIGN §2) are **Elad's**.
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
**Status:** the **web tier is feature-complete** — auth, profile, **daily check-in**, dashboard, history, the Forum (CRUD + **edit/delete your own post**), the frontend (CSRF + a distinct visual identity), **Week-9 logging**, and the concurrency-hardened thin `db.py` CRUD. The 3 containers build and run (`docker compose up --build`) with **fault tolerance** (restart policies + healthcheck `start_period`; `web` boots and degrades even if `ai` is down). The `ai` `/predict` is a contract-shaped placeholder until Shiri's model lands; `db` is a stock `mongo:7` whose schema / indexes / auth / seeding are Elad's.

## Sync points (when to coordinate)
1. **Kickoff** — confirm the split, run the stack, claim your PERSON file.
2. **Contract change** — anyone touching a shared contract (above) flags it in the PR + the group chat.
3. **Pre-demo** (before 16 Jul) — integrate; the MVP runs end-to-end.
4. **Pre-submit** (before 23 Aug) — freeze, full test suite, report + video.

## Plan & rubric
Phased build plan: [`docs/ROADMAP.md`](docs/ROADMAP.md). Grading rubric (80 + 10 + 10): [`docs/FEEDBACK.md`](docs/FEEDBACK.md).
