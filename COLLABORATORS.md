# Work Smarter, Not Harder — Team Collaboration Guide

> **Read this before writing code.** Who owns what, how the pieces connect (the contracts = the only
> fixed things), the workflow, and how to run the stack. Your detailed per-person roadmap is in `PERSON1/2/3.md`.

## Team
| Person | GitHub | Owns | Roadmap |
|---|---|---|---|
| **Shiri** | `shiriHaboob` | **AI brain** — model, `/predict`, recommendation engine, the dataset, the Forum cold-seed generator | [PERSON1.md](PERSON1.md) |
| **Lior** | `LiorBenSidi` | **Web app + data + observability + CI/CD** — the Flask **backend** (API · auth/sessions · validation · orchestration of ai+db) + the frontend (incl. the **direct-messages + live-DM-notifications Chat tab**) + the **whole data layer** (`services/db.py` CRUD, the Mongo indexes / `$jsonSchema` validators / auth config / backups / `db/seed.py`) + **Week-9 logging/observability** + the **`web`/`ai` container build & compose** + the **CI gate** (ruff → bandit → pytest) + the **CI/CD deploy pipeline** (GHCR build/push → SSH-deploy-to-Azure → Caddy HTTPS + `docker-compose.prod.yml`; dormant until the VM lands) | [PERSON2.md](PERSON2.md) |
| **Elad** | `EladNa1` | **Live deployment + scale + remaining Forum media** — the **live Azure deploy** (provision the VM + its GitHub secrets, make the GHCR packages public, UptimeRobot monitor, run the deploy demo — the pipeline *code* is in the repo, see Lior) + the test-runner service, the remaining **Forum media/attachments** (images/video + file-size limits) and **upvote/downvote notifications**, `flask-limiter` on the other public routes, stress / cross-container tests | [PERSON3.md](PERSON3.md) |
| **Shared** | all three | **Tests** — **Lior wrote the web + data integration / system / security tests** (auth · profile · check-in · dashboard · history · forum flows · the real-Mongo IT · the web→ai→db e2e) **and the CI gate**; each owner adds their plane's unit tests (Shiri = AI). **Elad owns the live cross-container test-runner + stress (locust).** | — |

Roles are **containers/aspects**, not a rigid feature list — see "Freedom" below.

## How it fits together — the contracts (the ONLY fixed shared things)
These are the seams between owners. Change one → update `docs/DESIGN.md` **and tell the team** (a "sync point").
- **`web → ai`** — `POST /predict {features} -> {state, proba, recommendations}` (DESIGN §3).
- **`web → db`** — `web` calls the **`services/db.py` functions** (the data API). The **whole data layer** — CRUD + the Mongo internals (indexes, `$jsonSchema` validators, auth config, `db/seed.py`; collections `users / profiles / analysis_history / forum_posts`, DESIGN §2) — is **Lior's**.
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
**Status:** the **web tier is feature-complete** — auth, profile, **daily check-in**, dashboard, history, the Forum (CRUD + **edit/delete your own post**), **direct messages + live DM notifications** (the Chat tab: conversations · threads · generative avatars · a polling notification pulse · an anti-spam messaging rate-limit), the frontend (CSRF + a distinct visual identity), **Week-9 logging**, and the concurrency-hardened thin `db.py` CRUD. The 3 containers build and run (`docker compose up --build`) with **fault tolerance** (restart policies + healthcheck `start_period`; `web` boots and degrades even if `ai` is down). The whole stack is **proven live end-to-end** (a real web→ai→db request path 12/12, the real-Mongo IT 6/6, Week-9 logging emitting in-container). The `ai` `/predict` is a contract-shaped placeholder until Shiri's model lands; `db` is a stock `mongo:7` whose **data layer is Lior's** (indexes, `$jsonSchema` validators, auth config, seed). The **CI/CD deploy pipeline** (GHCR build/push → SSH-deploy to the Azure VM → Caddy HTTPS, auto-rollback; [`docs/CICD_REPORT.md`](docs/CICD_REPORT.md)) is also built (Lior). **Open lanes:** Shiri — the real model behind `/predict` + the Forum cold-seed content; Elad — the **live** Azure deploy + demo, the remaining Forum media/attachments (images/video + file-size limits) + upvote/downvote notifications, stress, the test-runner. (Online-Forum §10 status: posts/comments/anonymity/post-votes + P2P DM + live DM notifications + anti-spam messaging rate-limit built; media, vote notifications, comment votes, a received-engagement metric and fuller cold-seeding open — see [`docs/FEEDBACK.md`](docs/FEEDBACK.md) §2.)

## Sync points (when to coordinate)
1. **Kickoff** — confirm the split, run the stack, claim your PERSON file.
2. **Contract change** — anyone touching a shared contract (above) flags it in the PR + the group chat.
3. **Pre-demo** (before 16 Jul) — integrate; the MVP runs end-to-end.
4. **Pre-submit** (before 23 Aug) — freeze, full test suite, report + video.

## Plan & rubric
Phased build plan: [`docs/ROADMAP.md`](docs/ROADMAP.md). Grading rubric (80 + 10 + 10): [`docs/FEEDBACK.md`](docs/FEEDBACK.md).
