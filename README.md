# Work Smarter, Not Harder

An **AI-powered sports-coaching platform** — WSML final project (Technion 00950219).
Athletes enter profile + recovery metrics; a **local Random Forest classifier** predicts a training-readiness
state (a small set of states — e.g. Ready / Moderate / Recovery-Needed — finalized during data exploration); a
recommendation engine turns that into action plans, workouts, program-balance analysis, and calorie targets.

**Team (Git Push & Pray):** Lior Ben Sidi · Shiri Haboob · Elad Nachalieli
**Full spec:** [`docs/PROPOSAL.md`](docs/PROPOSAL.md) (the submitted proposal).
**Presentation kit:** [`presentation/`](presentation/) — deck, speaker script, notes, Q&A, demo shot-list, submission checklist (start at [`presentation/README.md`](presentation/README.md)).

## Try it live
Deployed over HTTPS at **[app.worksmarternotharder.dev](https://app.worksmarternotharder.dev)** — register an
account and use it in any browser. It's an **installable PWA**, so you can add it to your phone's home screen and
it opens full-screen with its own icon + splash (no browser chrome), just like a native app:

- **iPhone (Safari):** open the link → **Share** → **Add to Home Screen** → **Add**.
- **Android (Chrome):** open the link → **⋮** menu → **Install app** (or **Add to Home screen**) → **Install**.

No install is required to use it — that's just the optional app-like shortcut. (There is deliberately **no Android
APK / Play Store build**; the PWA is the supported way onto a phone.)

## Architecture (3 containers — only `web` is exposed)
| Container | Role |
|---|---|
| `web/` | Flask frontend + authentication (werkzeug hashing) + API. **The only user-facing container.** |
| `db`   | MongoDB — users, profiles, programs, analysis history. Internal only. |
| `ai/`  | Random Forest inference + recommendation engine, behind a **bounded job queue + process pool**. Internal REST (`POST /predict`). |

Course rules the architecture is built to satisfy: ≥3 communicating containers, only `web` exposed, local AI model
(no external API), all 5 test types, fault tolerance, parallel scaling, password hashing + injection defense.

### The AI job queue (rubric §2, +5)
`POST /predict` does not score inline. It enqueues onto a **bounded** queue worked by a `ProcessPoolExecutor`
([`ai/jobqueue.py`](ai/jobqueue.py)), so concurrent callers are scored **in parallel across cores** instead of
serialized. A *process* pool, not threads: the GIL stops CPU-bound scoring from overlapping across threads —
measured at **0.96×** for threads vs **3.58×** for processes.

- The model itself lives behind one seam, [`ai/inference.py`](ai/inference.py)`:predict_one` — the pool imports it
  by name, so it stays a plain module-level function.
- **Bounded on purpose.** Past `AI_QUEUE_MAX_PENDING` the queue sheds with `503`, which `web` already treats as
  "ai unavailable" and degrades. An unbounded backlog grows memory without limit and scores jobs whose callers
  have already timed out — shedding early is what keeps the p95 honest.
- `ai` runs **one** gunicorn worker with threads: the job store is in-memory, so a second worker would own a
  second store. Parallelism comes from the pool, not from workers.

| Endpoint (internal) | Purpose |
|---|---|
| `POST /predict` | synchronous scoring — **unchanged response shape** (`state` · `proba` · `recommendations`) |
| `POST /jobs` · `GET /jobs/<id>` | fire-and-forget enqueue + result read-back |
| `GET /queue/stats` | depth, pool size, counters (drives the scaling before/after) |

### Scaling (measured, not asserted)
Two multiplying axes — full numbers + how to reproduce: [`docs/SCALING_REPORT.md`](docs/SCALING_REPORT.md).

| Axis | Knob | Result |
|---|---|---|
| Vertical — the pool inside one container | `AI_QUEUE_WORKERS` 1 → 4 | **2.86×** throughput, p95 halved |
| Horizontal — replicas | `docker compose ... --scale ai=2` | **1.60×** throughput (Docker service-DNS round-robin) |

```sh
docker compose -f docker-compose.yml -f docker-compose.scale.yml up --build --scale ai=2
```

> `GET /jobs/<id>` is **not** replica-safe — the job store is per-container, so the read round-robins to a replica
> that never saw the job. `web` only ever calls `/predict`, which is, so scaling out is safe. See
> [`docker-compose.scale.yml`](docker-compose.scale.yml).

## Repo layout
```
web/      Flask web app + the whole data layer (built)
ai/       Random Forest + recommendation engine (Shiri — placeholder today),
          behind jobqueue.py (bounded queue + process pool) and inference.py (the model seam)
tests/    Unit_Tests · Integration_Tests · System_Tests · Stress_Tests · Security_Tests
scripts/  setup-hooks.sh · scaling_benchmark.py (stdlib-only load driver)
docs/     PROPOSAL · GUIDELINES · DESIGN · ROADMAP · REPORT · SCALING_REPORT · JOB_QUEUE_PLAN
          CICD_REPORT · DEPLOY_DEMO · AUTH_TESTING · meeting-notes
```
The web + data + CI/CD layers, the job queue, scaling and the live Azure deploy are built; `ai/` (Shiri's model)
is the remaining build — all via pull requests (see below).

## Getting started (first-time, every clone)
**New here? → [`GETTING_STARTED.md`](GETTING_STARTED.md)** — clone · run the stack · find your part · the loop (≈5 min). It also covers the gate setup below.

After cloning, enable the local quality gate so the course's checks run **before** you commit (it mirrors CI):
```sh
sh scripts/setup-hooks.sh                 # enable the shared git hooks (.githooks/)
pip install -r requirements-dev.txt        # in your venv: pinned ruff + bandit + pytest
```
`git commit` then runs ruff (incl. **no `print()`** — use `logging`) + bandit; `git push` runs the tests. Full detail: [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Run it
```sh
cp .env.example .env            # sets SECRET_KEY (never commit .env)
docker compose up --build       # 3 containers → open http://localhost:8000/health
```

**Dev switches** (both default off; neither affects real users — full guide [`docs/AUTH_TESTING.md`](docs/AUTH_TESTING.md)):
- **Email mock ⇄ live = `SMTP_HOST`** — unset → login-OTP / signup-verify / reset codes are shown on screen + logged (no mailbox; teammates + grading use this); set `SMTP_*` + `MAIL_FROM` in `.env` → codes are emailed only. Every auth-mode var (`OTP_ENABLED`, `REGISTER_VERIFY_EMAIL`, …) passes through from `.env`; `curl localhost:8000/auth/config` reports `email_mode`.
- **Viewport desktop ⇄ mobile = the `?debug=1` panel** — append `?debug=1` → a ⚙ **Debug tools** panel previews the real mobile layout in an iframe on desktop. Dev-only, never shown to normal users.

## Run the tests
```sh
python -m pytest tests/         # full suite — runs on any machine (no local paths)
```
All five course test types live under `tests/` and run on every PR. A handful are **environment-gated** — they
skip without their dependency and run the moment it exists (they are not unwritten):

```sh
# the cross-container harness: boots web+db+ai + a test-runner container, exits with the runner's code
docker compose -f docker-compose.yml -f docker-compose.test.yml up --build --exit-code-from tests

TEST_MONGO_URI=mongodb://localhost:27017 pytest tests/Integration_Tests/test_db_mongo.py  # real Mongo
E2E_BASE_URL=http://localhost:8000       pytest tests/System_Tests                        # live stack
```
`AI_BASE_URL` un-skips the live job-queue suite (real worker processes, concurrent `/predict`, a burst shedding
with 503). The harness above sets it to `http://ai:5000` **inside** the compose network — `ai` publishes no host
port, so it is not reachable from your machine by design.

**Guard tests.** Some invariants are cheap to break by accident and expensive to discover in production — only
`web` is published, the queue stays bounded, the pool stays *processes*, `/predict` still goes through the queue,
`predict_one` keeps its shape, the CPU-burning benchmark never ships as the real model. Those live in
`test_deploy_contract.py`, `test_ai_queue_contract.py` and `test_scale_contract.py`, so a breaking change fails a
PR rather than a container. Each was verified by **breaking its invariant on purpose** and confirming the guard
went red — a guard that cannot fail is decoration.

## Workflow — PRs only
`main` is protected: **no direct pushes.** All changes land via a pull request from a branch. See
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Deployment (CI/CD → Azure)
Every push to `main` runs an automated pipeline ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) that takes the
dockerized stack from commit to a running container on an Azure VM, served over HTTPS. The app exposes two probes: `GET /health`
(trivial **liveness** — `200 {"status":"ok","service":"web"}`, no Mongo, so it boots before the DB layer) and `GET /ready` (**readiness** — pings
Mongo, `503` if the DB is down). The container healthcheck uses `/health`; the post-deploy gate + external monitor use `/ready`.
Full requirement-by-requirement mapping: [`docs/CICD_REPORT.md`](docs/CICD_REPORT.md).

**Pipeline stages** (a PR runs only stages 1–2 — it never deploys):
```
push/PR ─▶ 1. checks      ruff + bandit + pytest (real mongo:7 service)     ← gates everything
push/PR ─▶ 2. compose-e2e boots web+db+ai + a test-runner container, drives the real wire path
push    ─▶ 3. build       docker build web + ai (cached) ─▶ GHCR (latest + <short-sha>)
push    ─▶ 4. deploy      ssh → VM: docker compose pull && up -d  (VM pulls, never builds)
push    ─▶ 5. verify      curl --fail https://<FQDN>/ready  ← fails the run + auto-rolls-back if unhealthy
manual  ─▶    stress      locust, on demand (needs a live stack; never a merge gate)
```
Both `checks` **and** `compose-e2e` gate the build, so a broken `web → ai → db` wire path can never reach GHCR
or the VM. The `stress` job is `workflow_dispatch`-only — run it with `gh workflow run ci.yml --ref main`.
Caddy (in [`docker-compose.prod.yml`](docker-compose.prod.yml)) terminates TLS with an auto-renewing Let's Encrypt
certificate and redirects HTTP→HTTPS; the VM runs the prod compose, which **pulls** the GHCR images rather than building.

**GitHub Actions secrets & variables** (names only — values live only in repo settings):

| Kind | Name | Purpose |
|---|---|---|
| Secret | `SSH_PRIVATE_KEY` | dedicated deploy key for the VM's `deploy` user (never a personal key) |
| Secret | `APP_SECRET_KEY` | Flask `SECRET_KEY`, injected into the VM's `.env` at deploy time |
| Secret | `SMTP_USER` | Brevo relay login — *optional*; set it + `SMTP_PASS` to turn on real inbox email (OTP/reset). Unset → safe log backend |
| Secret | `SMTP_PASS` | Brevo SMTP key — *optional*; its presence is the switch that flips email from log-backend to real Brevo delivery |
| Variable | `SSH_HOST` | the VM's FQDN (`<label>.<region>.cloudapp.azure.com`) — the **SSH/deploy target** |
| Variable | `DEPLOY_ENABLED` | the deploy switch. **The deploy job runs only when `SSH_HOST` is set AND `DEPLOY_ENABLED == 'true'`**; anything else (unset included) → deploy skipped, `main` stays green. Flip live/off with one `gh variable set DEPLOY_ENABLED --body true|false`, never touching `SSH_HOST` |
| Variable | `SITE_ADDRESS` | *optional* — the **public** HTTPS address (TLS cert + health check + monitor + email links). Set it to serve the app at your own domain (e.g. `app.worksmarternotharder.dev`, CNAME'd to the FQDN); unset → falls back to the Azure FQDN |
| — (built-in) | `GITHUB_TOKEN` | authenticates the GHCR push automatically — no PAT, no signup |

`SSH_USER` is a **variable** (default `azureuser`) — override it only if your VM uses a different login. `SSH_HOST` is a **variable**, not a
secret — a hostname needs no masking. The `SMTP_*` pair is optional: with it unset the app writes the login code to its
log (fine for the demo); set both to deliver real Brevo email from the authenticated `worksmarternotharder.dev` domain.

> **One-time, after the first `build` runs:** the pushed GHCR packages (`work-smarter-web`, `work-smarter-ai`) are
> **private** by default (this is a private repo). Set each to **Public** (package → *Package settings → Change
> visibility*) so the VM can `docker compose pull` them without storing a registry credential on the host.

**VM provisioning:** the instructor provisions **one Azure VM per group** (ports 22/80/443 only, `deploy` user, key-only
SSH via cloud-init) and gives you its FQDN. You generate a **dedicated** deploy keypair
(`ssh-keygen -t ed25519 -f groupNN_deploy -N ""`), send the instructor the `.pub`, store the private key as
`SSH_PRIVATE_KEY`, and set `SSH_HOST` to the FQDN. Idle VMs auto-stop; start yours from the Azure portal (Technion login).

### Serving at a custom domain (optional)
The app is already R10-compliant served at the **Azure FQDN** — a custom domain is optional polish. Our domain
`worksmarternotharder.dev` plays **two independent roles**:

**1 · App — the HTTPS front door** (point a subdomain at the VM; Caddy gets its cert):
1. Pick a subdomain, e.g. `app.worksmarternotharder.dev` (the root apex can't `CNAME`).
2. At the DNS provider (Name.com) add a **`CNAME`**: host `app` → value `<the Azure FQDN>` (`<label>.<region>.cloudapp.azure.com`).
   `CNAME`-to-FQDN (not an `A` record to the IP) survives an Azure IP change.
3. Set the GitHub **variable** `SITE_ADDRESS` = `app.worksmarternotharder.dev`.
4. Push to `main` → the deploy injects `SITE_ADDRESS` into the VM's `.env` → **Caddy obtains a Let's Encrypt cert** for it
   (HTTP-01 over :80) and serves the app there. `SSH_HOST` stays the FQDN (the SSH target); the two may differ.
- **Skip this** → leave `SITE_ADDRESS` unset and the app serves at the Azure FQDN (still valid HTTPS, R10).

**2 · Email — sender authentication** (so OTP / password-reset mail reaches real inboxes):
1. In Brevo, **authenticate the domain** (Senders, Domains & IPs → Domains). It prints a **brevo-code `TXT`**, two
   **DKIM `CNAME`s** (`brevo1/brevo2._domainkey`), and a **DMARC `TXT`** (`_dmarc`) — add all four at Name.com.
2. Add a sender `no-reply@worksmarternotharder.dev` (auto-verifies once the domain is authenticated).
3. Set the `SMTP_USER` / `SMTP_PASS` secrets (Brevo relay creds); the deploy injects them and `MAIL_FROM`
   = `Work Smarter <no-reply@worksmarternotharder.dev>`. Unset → the app uses its log backend (login still works).
- Email is **not** a course requirement — deliverability is an enhancement. Links inside the mail point at `SITE_ADDRESS`.

## For AI agents (any tool)
The workflow is **enforced for every tool and human**: `main` is branch-protected, so direct pushes are
rejected and changes land only via a PR that passes CI — no agent can bypass it, whatever it reads. For
*awareness*, each tool reads its own file; all point to [`CLAUDE.md`](CLAUDE.md) + [`CONTRIBUTING.md`](CONTRIBUTING.md)
as the source of truth:

| Tool | File it reads |
|---|---|
| Claude Code | [`CLAUDE.md`](CLAUDE.md) |
| Codex (+ others via the cross-tool standard) | [`AGENTS.md`](AGENTS.md) |
| GitHub Copilot | [`.github/copilot-instructions.md`](.github/copilot-instructions.md) |
| Cursor | [`.cursor/rules/work-smarter.mdc`](.cursor/rules/work-smarter.mdc) (also reads `AGENTS.md`) |

**Using a tool not listed?** Read `CLAUDE.md` + `CONTRIBUTING.md` — the rules apply regardless, and branch
protection enforces them either way. (We intentionally don't add a separate config file per niche tool — it
clutters the repo and drifts; the README + `AGENTS.md` are the catch-all.)

## Status
Proposal graded **100/100**. Rubric: [`docs/GUIDELINES.md`](docs/GUIDELINES.md) — 75 build · **+5 Job Queue** ·
+10 Forum · +10 Deploy & CI/CD.

**Built and live.** The web tier, the whole data layer, the online Forum (posts · comments · votes · anonymity ·
P2P direct messages · media attachments · SSE-pushed notifications · a per-user **received-engagement total**
on the profile), Week-9 logging, the 3-container build, the CI gate, the cross-container test-runner, the
**AI job queue (+5)** (bounded + self-healing pool), **measured scaling**, and the CI/CD pipeline
auto-deploying every green `main` to Azure over HTTPS. Suite: **697 passing / 36 environment-gated** (733 collected).

**Remaining:** the Random Forest behind `POST /predict` (Shiri — the contract-shaped placeholder is in place, so
the queue and `web` already integrate against it) and forum cold-seed content. Risk assessment and the honest
"what we did *not* mitigate" list: [`docs/REPORT.md`](docs/REPORT.md) §5.

Final project due **23 Aug 2026** (demo Week 12, present 16 July).
