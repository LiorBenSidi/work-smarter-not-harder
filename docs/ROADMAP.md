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
Azure; public domain; scale horizontally via gunicorn workers + `ai` replicas (`--scale ai=N`).
**Done when:** a push to `main` → tests pass → the Azure URL serves the update.
*Banks the full +10. The CI-only half (5 pts) is already secured by the existing gate.*

### Complete the 80 — rest of F1–F9
**Scope:** F5 workout generator · **F7 action plan (with F6's balance rule
folded in)** · F9 history · F8 fleshed out (full dashboard + history). Fault tolerance + rate-limiting + input validation + NoSQL-injection
defense across all endpoints.
**Done when:** the whole proposal (minus stretch) runs on Docker; the feature×test matrix is complete; the risk
report is concrete. **= the 80.**

### Forum (+10) — *built last, in 3 cuttable slices; partial credit accrues per slice*
Same stack as the app (Flask + Mongo + Docker) **plus a real-time layer** — SSE needs no new dependency and
covers one-way feeds/notifications; Flask-SocketIO adds true bidirectional sockets for DM (a dependency →
audit-then-`!`-install when you reach it). All 8 sub-features are needed for the full +10, but Noam gives
**partial credit per feature**, so build hardest-last:

- **3a — Forum content** (backbone): posts (title/body + **image/video** upload) · comments · **anonymity toggle** · **cold-seeding** (seed script: fake accounts/posts/threads) · **rate-limit + file-size caps** (Flask-Limiter + upload validation). Mostly CRUD + uploads + a fixture. → ships a working, seeded forum.
- **3b — Engagement + live feed**: **up/down-votes** on posts+comments · per-user **engagement dashboard** · make the feed **real-time** (introduce the SSE/WebSocket layer here). → ships a live, votable forum.
- **3c — Messaging** (hardest, most cuttable): secure **P2P DM** (text/image/video) · **live notifications** for new DMs + votes (reuses 3b's real-time layer). → ships real-time DM + notifications.

**Tests (each slice):** unit (vote tally · anonymity · size-limit) · integration (post→comment→notify) · security (rate-limit blocks a flood · oversized upload rejected · DM auth-gated + private) · stress (post/vote flood → 429, not a crash).
**Done when:** the slices you ship are integrated, tested, auto-deployed. **Cut line:** if time runs short, 3a (+3b) alone still banks most of the +10 — the app stays a viable 80+10 product without 3c.

## Engineering standards (every phase)
- **TDD-first**; all 5 test types + a feature×test matrix; a broken test is **deleted, not commented out**; tests
  run on any machine (env vars, no local paths).
- **Docker:** ≥3 containers, only `web` exposed (host 8000, never 5000 — macOS AirPlay); RF **baked into the image**
  (joblib, pinned sklearn); **scaling = `ai` replicas + gunicorn workers** (multiprocessing only for measured CPU-heavy work).
- **Security:** hash passwords (werkzeug); auth-gate endpoints; rate-limit; validate input; defend NoSQL injection.
- **Fault tolerance:** an AI / Mongo / wearable failure must degrade, not crash the app.
- **Process:** regular, informative commits from **all 3** members (history is graded); never commit `.env`; repo
  stays outside OneDrive.

## Parallel execution (everyone starts day 1)
The contracts are fixed and stubbed, so the three planes build independently from the first commit — nobody waits:
- **Shiri (`ai/`)** — standalone; builds + tests the model and `/predict` via the test client.
- **Lior (`web/`)** — builds against the `/predict` stub (already returns the contract) + the Mongo container.
- **Elad (infra)** — the skeleton runs, so Azure setup, `docker-compose.test.yml`, and the stress + cross-container test harness all start now.

The only coordination points are the seams (`/predict` shape, `db.py`'s function API, only-`web`-exposed) — changing one is a **sync point** (flag it in the PR + the group chat).

## Requirements coverage (TA notes + guidelines + Noam's rubric)
| Requirement | Status | Owner |
|---|---|---|
| Docker, runs first-try anywhere | ✅ skeleton | Elad |
| ≥3 communicating containers, only `web` exposed | ✅ | Elad |
| Local AI model, baked into image, pinned sklearn | ⬜ | Shiri |
| All 5 test types — per-feature, run-anywhere, no-cheating | 🟡 scaffolds + matrix | all |
| `docker-compose.yml` **and** `docker-compose.test.yml` | 🟡 both **scaffolded** (test = env override → `worksmarter_test`); test-runner service TODO | Lior (scaffold) · Elad (runner) |
| `debug` flag toggles debug mode | 🟡 env wired; confirm it toggles | Lior |
| Password hashing (werkzeug) | ✅ | Lior |
| Input validation (routes) + injection-safe queries (thin `db.py` CRUD) | ✅ | Lior |
| Rate-limit / anti-spam (flask-limiter) | ⬜ | Elad |
| Fault tolerance + **isolation tested** (stop ai/db → web survives) | 🟡 `ai_client` degrades; kill-container tests TODO | Elad + all |
| Parallel programming + scaling — multiprocessing batch · replicas/workers · multi-machine (Swarm / Azure VM) · **queue-free** | 🟡 concrete plan | Shiri (parallel code) · Elad (scaling) |
| Stress tests (decide what can crash) | ⬜ | Elad |
| GitHub: regular commits from **all 3**, meaningful messages | 🟡 in progress | all |
| Report (app + features×tests + **risk assessment**) | ⬜ | all (Elad: risk) |
| Demo video of using the app | ⬜ | all |
| Azure VM deploy + CI/CD auto-deploy (+10; base deploy optional) | 🟡 CI live (+5); Azure TODO | Elad |
| Online Forum — real-time, 8 sub-features (+10) | 🟡 Lior's CRUD+UI (posts/comments/votes, anonymity) done; real-time + seeding TODO | Lior (CRUD/UI ✅) · Elad (real-time) · Shiri (seeding) |
| Present 16 Jul (6 min) · demo by Wk 12 · final 23 Aug | ⬜ | all |
| No shipped API keys | ✅ local model | Shiri |

Legend: ✅ done · 🟡 partial / in-progress · ⬜ not started.

## Status (2026-06-28)
Scaffold + branch-protected PR-only `main` + CI gate (ruff → bandit → pytest, no-false-green) + a local pre-commit
gate are live — that CI already earns the **5-pt CI-only** partial of the deploy +10.

**Live now:** the runnable 3-container skeleton (`docker-compose` + healthchecks + gunicorn, only `web` exposed),
the `web↔ai` glue (`ai_client`), the **F4 calorie** function (`ai/calories.py`), and the ratified split. The
**web tier is complete + polished**: auth / profile / dashboard / history / frontend + CSRF + responsive dark-light
theming + a11y + credential-hint tooltips (`/auth/config`), Forum CRUD/UI. The **thin `db.py` CRUD** is implemented
+ tested (incl. `ensure_indexes`, votes stored as a list, and a real-Mongo integration suite that skips until a DB
is up). **Still to build:** the RF model + real `/predict` + recommendation engine (Shiri); running the Mongo
container + perf indexes + auth, `docker-compose.test.yml`, rate-limiting, Azure deploy, the Forum real-time layer +
stress/cross-container tests (Elad); the daily check-in flow (Lior — blocked on the AI input contract). Due **23 Aug 2026**.
