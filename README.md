# Work Smarter, Not Harder

An **AI-powered sports-coaching platform** — WSML final project (Technion 00950219).
Athletes enter profile + recovery metrics; a **local Random Forest classifier** predicts a training-readiness
state (a small set of states — e.g. Ready / Moderate / Recovery-Needed — finalized during data exploration); a
recommendation engine turns that into action plans, workouts, program-balance analysis, and calorie targets.

**Team (Git Push & Pray):** Lior Ben Sidi · Shiri Haboob · Elad Nachalieli
**Full spec:** [`docs/PROPOSAL.md`](docs/PROPOSAL.md) (the submitted proposal).

## Architecture (3 containers — only `web` is exposed)
| Container | Role |
|---|---|
| `web/` | Flask frontend + authentication (werkzeug hashing) + API. **The only user-facing container.** |
| `db`   | MongoDB — users, profiles, programs, analysis history. Internal only. |
| `ai/`  | Random Forest inference + recommendation engine. Internal REST (`POST /predict`). |

Course rules the architecture is built to satisfy: ≥3 communicating containers, only `web` exposed, local AI model
(no external API), all 5 test types, fault tolerance, parallel scaling, password hashing + injection defense.

## Repo layout
```
web/     Flask web container (to build)
ai/      Random Forest + recommendation engine (to build)
tests/   Unit_Tests · Integration_Tests · System_Tests · Stress_Tests · Security_Tests
docs/    PROPOSAL.md (spec) · DESIGN · ROADMAP · FEEDBACK (rubric) · meeting-notes
```
This is a starting scaffold — the team fills it in via pull requests (see below).

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

## Run the tests
```sh
python -m pytest tests/         # full suite — runs on any machine (no local paths)
```

## Workflow — PRs only
`main` is protected: **no direct pushes.** All changes land via a pull request from a branch. See
[`CONTRIBUTING.md`](CONTRIBUTING.md).

## Deployment (CI/CD → Azure)
Every push to `main` runs an automated pipeline ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) that takes the
dockerized stack from commit to a running container on an Azure VM, served over HTTPS. The app exposes two probes: `GET /health`
(trivial **liveness** — `200 {"status":"ok"}`, no Mongo, so it boots before the DB layer) and `GET /ready` (**readiness** — pings
Mongo, `503` if the DB is down). The container healthcheck uses `/health`; the post-deploy gate + external monitor use `/ready`.
Full requirement-by-requirement mapping: [`docs/CICD_REPORT.md`](docs/CICD_REPORT.md).

**Pipeline stages** (a PR runs only stage 1 — it never deploys):
```
push/PR ─▶ 1. checks     ruff + bandit + pytest (real mongo:7 service)      ← gates everything
push    ─▶ 2. build      docker build web + ai (cached) ─▶ GHCR (latest + <short-sha>)
push    ─▶ 3. deploy     ssh → VM: docker compose pull && up -d  (VM pulls, never builds)
push    ─▶ 4. verify     curl --fail https://<FQDN>/ready   ← fails the run + auto-rolls-back if unhealthy
```
Caddy (in [`docker-compose.prod.yml`](docker-compose.prod.yml)) terminates TLS with an auto-renewing Let's Encrypt
certificate and redirects HTTP→HTTPS; the VM runs the prod compose, which **pulls** the GHCR images rather than building.

**GitHub Actions secrets & variables** (names only — values live only in repo settings):

| Kind | Name | Purpose |
|---|---|---|
| Secret | `SSH_PRIVATE_KEY` | dedicated deploy key for the VM's `deploy` user (never a personal key) |
| Secret | `APP_SECRET_KEY` | Flask `SECRET_KEY`, injected into the VM's `.env` at deploy time |
| Secret | `SMTP_USER` | Brevo relay login — *optional*; set it + `SMTP_PASS` to turn on real inbox email (OTP/reset). Unset → safe log backend |
| Secret | `SMTP_PASS` | Brevo SMTP key — *optional*; its presence is the switch that flips email from log-backend to real Brevo delivery |
| Variable | `SSH_HOST` | the VM's FQDN (`<label>.<region>.cloudapp.azure.com`) — the **SSH/deploy target**. **Until this is set, the deploy job is skipped and `main` stays green** |
| Variable | `SITE_ADDRESS` | *optional* — the **public** HTTPS address (TLS cert + health check + monitor + email links). Set it to serve the app at your own domain (e.g. `app.worksmarternotharder.dev`, CNAME'd to the FQDN); unset → falls back to the Azure FQDN |
| — (built-in) | `GITHUB_TOKEN` | authenticates the GHCR push automatically — no PAT, no signup |

`SSH_USER` is the same for every group (`deploy`) and is hardcoded in the workflow. `SSH_HOST` is a **variable**, not a
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
Proposal submitted; build in progress. Final project due **23 Aug 2026** (demo Week 12, present 16 July).
