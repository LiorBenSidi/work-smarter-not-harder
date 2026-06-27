# Build Roadmap — Work Smarter, Not Harder

Phased so we always have a viable product (per Noam's feedback). **Every phase is independently shippable:**
tested, Dockerized, and — once the deploy milestone lands — auto-deployed to Azure on green CI.

**Driving spec:** the submitted [`PROPOSAL.md`](PROPOSAL.md) + Noam's rubric ([`FEEDBACK.md`](FEEDBACK.md)):
**80** = the whole app (F1–F9, no stretch goals) on Docker · **+10** real-time Forum · **+10** Azure deploy + CI/CD.
Penalties: −5 / bug, −5 / week late. Partial credit per feature; you needn't do it all (this is the bar for a perfect 100).

## Scope decision — pending Noam's OK
**F6 (Program-Balance Analysis) folds into F7 (Action Plan)** as a single rule, rather than a standalone feature:
F5 already generates balanced programs, and F7 already surfaces the same insight (e.g. "add chest volume").
Emailed Noam to confirm this keeps full credit. **Fallback if he wants a distinct feature:** swap F6 for
*training-trend analysis* over saved history (same data-analysis concept, reuses the history store). Until he
replies, build F6 as a rule inside F7.

## Phase 0 — MVP (must come first)
**Goal:** prove the architecture + the AI heart, end-to-end on Docker.
**Scope:** F1 auth (register / login / logout, werkzeug hashing) · F2 profile · **F3 readiness** (Random Forest
baked into the `ai` image; `web` → `ai` `POST /predict`) · **F4 calorie** (Mifflin-St Jeor, closed-form) · minimal F8 dashboard (readiness + calories) · MongoDB persistence ·
`docker-compose` with 3 containers (only `web` exposed — host **8000** → container 5000).
**Done when:** `docker compose up --build` → register → enter profile → see a readiness class **and a calorie target** on the dashboard;
CI green; first real tests in all five dirs; the feature×test matrix is started; the `debug` flag is wired.

> **Phase 0 vs the proposal's §15 MVP:** Phase 0 is a thin architecture-proving slice. With F4 added it now covers the proposal's §15 "Minimum Working Version" **except the heavier Workout-generator (F5)**, which lands first in *Complete the 80* below — so the full §15 MVP is done by the end of that workstream. **Nothing in the proposal is dropped.**

## After Phase 0 — three workstreams
Order is **open** (recommended as written below; final sequencing TBD). The only hard constraint: **Deploy can't
start until Phase 0 exists** — you can't auto-deploy nothing.

### Deploy + CI/CD (+10) — *recommended next*
**Goal:** every green commit auto-deploys to the supplied Azure VM, publicly.
**Scope:** extend the existing CI (ruff → bandit → pytest) with a deploy job that, on green `main`, redeploys on
Azure; public domain; scale via the multiprocessing / `ai`-replica design.
**Done when:** a push to `main` → tests pass → the Azure URL serves the update.
*Banks the full +10. The CI-only half (5 pts) is already secured by the existing gate.*

### Complete the 80 — rest of F1–F9
**Scope:** F5 workout generator · **F7 action plan (with F6's balance rule
folded in)** · F9 history · F8 fleshed out (full dashboard + history). Fault tolerance + rate-limiting + input validation + NoSQL-injection
defense across all endpoints.
**Done when:** the whole proposal (minus stretch) runs on Docker; the feature×test matrix is complete; the risk
report is concrete. **= the 80.**

### Forum (+10) — *recommended last (biggest lift, most cuttable)*
**Scope:** posts (title / body / image / video) · anonymity toggle · comments · up/down-votes + an engagement
dashboard · secure P2P DM · **real-time** notifications · anti-spam rate-limit + file-size caps · cold-seeding.
Real-time via WebSocket / SSE (no manual refresh).
**Done when:** the real-time forum is integrated, tested, deployed. If it overruns, the app is already a viable
80+10 product without it (the swap-a-feature email option applies here too).

## Engineering standards (every phase)
- **TDD-first**; all 5 test types + a feature×test matrix; a broken test is **deleted, not commented out**; tests
  run on any machine (env vars, no local paths).
- **Docker:** ≥3 containers, only `web` exposed (host 8000, never 5000 — macOS AirPlay); RF **baked into the image**
  (joblib, pinned sklearn); **CPU-bound inference → multiprocessing** (the scaling story).
- **Security:** hash passwords (werkzeug); auth-gate endpoints; rate-limit; validate input; defend NoSQL injection.
- **Fault tolerance:** an AI / Mongo / wearable failure must degrade, not crash the app.
- **Process:** regular, informative commits from **all 3** members (history is graded); never commit `.env`; repo
  stays outside OneDrive.

## Status (2026-06-25)
Scaffold + branch-protected PR-only `main` + CI gate (ruff → bandit → pytest, no-false-green) + a local pre-commit
gate are live — that CI already earns the **5-pt CI-only** partial of the deploy +10. Still to build: the `web` /
`ai` containers, the Random Forest model + `/predict`, `docker-compose`, and the features. Due **23 Aug 2026**.
