# CI/CD Report — Work Smarter, Not Harder

Maps the CI/CD assignment requirements (R1–R10) to where and how this repository satisfies them.
Pipeline: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) · Prod stack:
[`docker-compose.prod.yml`](../docker-compose.prod.yml) · TLS: [`Caddyfile`](../Caddyfile) · Demo run-sheet + UptimeRobot
setup + grader Q&A: [`DEPLOY_DEMO.md`](DEPLOY_DEMO.md).

**The app & its health endpoint.** *Work Smarter, Not Harder* is a 3-container Flask app (web + internal `ai`
inference + MongoDB). Only `web` is public. It exposes `GET /health` ([`web/app.py`](../web/app.py)) returning
`200 {"status":"ok","service":"web"}`, used by the container healthcheck, the pipeline's post-deploy check (R7), and the external
monitor (R9).

## Requirement mapping

| Req | How it is satisfied | Where |
|---|---|---|
| **R1.1** all source + Dockerfile/compose + pipeline in one repo | single repo | this repo |
| **R1.2** runs automatically on push to `main` | `on: push: branches:[main]` | `ci.yml` |
| **R1.3** PR runs but stops after tests (no deploy) | `checks` runs on `pull_request`; `build`/`deploy` gated `if: github.event_name == 'push'` | `ci.yml` |
| **R2.1/2.2** install deps + run tests; fail blocks the rest | `checks` job: ruff + bandit + `pytest tests/`; `build` has `needs: checks` | `ci.yml` |
| **R2.3** a real test (not a placeholder) | full `tests/` suite (Unit/Integration/System/Security) against a real `mongo:7` service | `tests/`, `ci.yml` |
| **R3.1/3.3** build image from Dockerfile, repo only | `docker build ./web`, `docker build ./ai` | `build` job |
| **R3.2** tag `latest` **and** an immutable short-SHA | `-t $IMG:latest -t $IMG:<short-sha>` (`${GITHUB_SHA::7}`) | `build` job |
| **R4.1/4.3** push to GHCR, both tags | `docker push` of both tags to `ghcr.io/<owner>/work-smarter-{web,ai}` | `build` job |
| **R4.2** auth via built-in token, no hard-coded creds | `docker login ghcr.io` with `GITHUB_TOKEN` + `permissions: packages: write` | `build` job |
| **R5.1** deploy over SSH after a successful push | `deploy` job: `ssh azureuser@$SSH_HOST` (the VM login user, via the `SSH_USER` var, default `azureuser`) | `deploy` job |
| **R5.2** VM **pulls** the image, never builds | `docker compose -f docker-compose.prod.yml pull && up -d`; prod compose uses `image:`, no `build:`, pinned to the commit SHA via `IMAGE_TAG` (reproducible, not a moving `:latest`). *Precondition:* the GHCR packages must be **public** (see caveats) so the VM pulls without a host credential | `deploy` job, `docker-compose.prod.yml` |
| **R5.3** idempotent redeploy | `pull && up -d` converges to the same state | `deploy` job |
| **R5.4** survives a VM reboot | `restart: unless-stopped` on every service | `docker-compose.prod.yml` |
| **R6.1** secrets as GitHub Actions secrets, injected at runtime | `SSH_PRIVATE_KEY`, `APP_SECRET_KEY` (secrets); `SSH_HOST` (variable) | repo settings, `deploy` job |
| **R6.2** no secret in repo/image/logs | `.env`, `prod.env`, `*_deploy` gitignored; key written to a file, GitHub masks secret values | `.gitignore`, `deploy` job |
| **R6.3** VM: key-only SSH | enforced by the instructor's cloud-init (verified by grader) | (instructor) |
| **R7.1/7.2** post-deploy health check on the deployed server | `curl --fail --retry 15 --retry-all-errors https://$SSH_HOST/ready` — `/ready` pings Mongo, so a pass proves the whole stack (not just that web answers); retries through the cold-boot TLS issuance | `deploy` job |
| **R8.1** any stage failing fails the whole run | `needs:` chain + default fail-fast | `ci.yml` |
| **R8.2** *(optional)* rollback on failed health check | **implemented** — the deploy records the last-good SHA on the VM; a failed `/ready` check re-deploys it (the run still ends red) | `deploy` job |
| **R9** external uptime monitor, ≤5 min, alert, down→up | **live** — UptimeRobot monitor `803532626` on the prod FQDN (since 17 Jul) | dashboard / live |
| **R10.1–10.5** valid auto-renewing Let's Encrypt HTTPS; HTTP→HTTPS | `caddy` service + `Caddyfile` (`reverse_proxy web:5000`) issues the cert for `SITE_ADDRESS` — the Azure FQDN by default, or a custom domain CNAME'd to it (wiring steps in the README); gunicorn stays internal | `docker-compose.prod.yml`, `Caddyfile` |

## What is live now vs. what activates with the VM

- **Live on the next push to `main` (no external setup):** `checks` → `build` → **GHCR push** (R1–R4). GHCR needs only
  the repo's own `GITHUB_TOKEN`, so R3/R4 are demonstrable immediately.
- **Gated behind an explicit switch:** the `deploy` job is **skipped** unless BOTH `SSH_HOST` (the VM FQDN) is set
  **and** the `DEPLOY_ENABLED` variable equals `'true'`. So `main` stays green during development (deploy off), and you
  go live by flipping one variable — `gh variable set DEPLOY_ENABLED --body true` — with no code change (the VM FQDN +
  `SSH_PRIVATE_KEY` + `APP_SECRET_KEY` must also be set). R5, R7, R9, R10 activate then; set it back to `false` to stop.

## Honest caveats / documented gaps

- **GHCR packages must be made public once** — images pushed by `GITHUB_TOKEN` from a private repo are private by
  default, and the VM's `docker compose pull` runs with no registry login. After the first `build`, set both packages
  to Public (or the VM would need a stored read-token, which we deliberately avoid). Until then, R5.2's pull can't
  succeed. This is a one-time UI step, not a code change.
- **`/health` (liveness) vs `/ready` (readiness).** `/health` returns `200` without touching Mongo (a course rule;
  `tests/Integration_Tests/test_auth_flow.py::test_default_store_app_serves_health` enforces it) and drives the
  *container* healthcheck. `/ready` pings Mongo and returns `503` when the DB is down; the **post-deploy gate (R7) and
  the external monitor target `/ready`**, so a green deploy proves the whole stack serves — not just that web answers.
- **R8.2 auto-rollback — implemented.** The deploy records the last-good SHA on the VM (`~/app/.last_good_sha`); if the
  post-deploy `/ready` check fails, it re-deploys that SHA so the VM is restored to the last healthy image. The run
  still ends red (R8.1 intact) — rollback repairs prod, it doesn't mask the failure. (The very first deploy has no
  prior SHA to roll back to.)
- **R9 monitor** and the **first Let's Encrypt issuance (R10)** require the live VM and a browser step (UptimeRobot
  account), so they are configured at provisioning time, not in code.
- The **live demo** (push a visible change → watch it reach the VM; break a PR test; show the monitor's down→up) is
  performed at grading, per the assignment's acceptance criteria.

## Beyond the rubric

- **Real transactional email (enhancement, not graded).** The app sends OTP + password-reset mail via Brevo from the
  authenticated `worksmarternotharder.dev` domain (SPF/DKIM/DMARC verified; Gmail inbox delivery confirmed). It is
  self-gating in the deploy: with the `SMTP_*` secrets unset the app falls back to the log backend (login still works);
  set them and real inbox delivery turns on. The app is *served* at the Azure FQDN (R10) — the domain is used only as
  the email FROM, so the two concerns stay cleanly separate.

## Evidence (from the live pipeline)

**A green `push`-to-`main` run — the full chain, deploy included**
[run 29705056423](https://github.com/LiorBenSidi/work-smarter-not-harder/actions/runs/29705056423) · `main` @ `14414d7` · 2026-07-19

| job | result |
|---|---|
| `checks` (ruff · bandit · pytest + `mongo:7`) | ✅ success |
| `e2e (browser · desktop + mobile)` | ✅ success |
| `cross-container stack (test-runner)` | ✅ success |
| `build & push image (GHCR)` | ✅ success |
| `deploy to Azure VM` | ✅ success |
| `stress (locust, on demand)` | ⏭ skipped (manual dispatch — R2.3) |

This is the shape every merge takes: green gates → images tagged `${GITHUB_SHA::7}` + `latest` → SSH deploy →
`/ready` probe against the FQDN.

**A red run that blocked the deploy — the gate doing its job (R2.2)**

Both examples below are pushes **to `main`**, i.e. runs that *would* have deployed. That matters: on a PR,
`build` is skipped by its own `github.event_name == 'push'` guard, so a PR proves the event fence (R1.3) but
says nothing about the test gate. These two prove the `needs:` chain.

*A red `checks` stops everything* —
[run 29207400240](https://github.com/LiorBenSidi/work-smarter-not-harder/actions/runs/29207400240) · `main` · 2026-07-12

| job | result |
|---|---|
| `checks` (ruff · bandit · pytest) | ❌ **failure** |
| `cross-container stack (test-runner)` | ⏭ skipped |
| `e2e (browser · desktop + mobile)` | ⏭ skipped |
| `build & push image (GHCR)` | ⏭ **skipped** |
| `deploy to Azure VM` | ⏭ **skipped** |

*A green `checks` but a red cross-container stack still stops the deploy* —
[run 29209297922](https://github.com/LiorBenSidi/work-smarter-not-harder/actions/runs/29209297922) · `main` · 2026-07-12

| job | result |
|---|---|
| `checks` | ✅ success |
| `cross-container stack (test-runner)` | ❌ **failure** |
| `e2e (browser · desktop + mobile)` | ✅ success |
| `build & push image (GHCR)` | ⏭ **skipped** |
| `deploy to Azure VM` | ⏭ **skipped** |

The second run is the one worth pointing at: the fast suite was **green**, and the deploy was still blocked —
by `compose-e2e`, the cross-container harness. That is exactly why `build` declares
`needs: [checks, compose-e2e]` rather than `needs: checks` alone. Unit tests run against injected in-memory
fakes and cannot see a broken `web → ai → db` wiring; the harness boots the real three containers and can. No
image was pushed and the VM was never contacted in either run.

**What the gate deliberately does *not* block: `e2e-browser`.** `build` needs `checks` and `compose-e2e` only,
so a red browser-e2e job does **not** stop a deploy — and three times it did not
([29497159256](https://github.com/LiorBenSidi/work-smarter-not-harder/actions/runs/29497159256),
[29492804611](https://github.com/LiorBenSidi/work-smarter-not-harder/actions/runs/29492804611),
[29275869078](https://github.com/LiorBenSidi/work-smarter-not-harder/actions/runs/29275869078): browser e2e red,
`build` + `deploy` both green). This is a **known trade-off, not an oversight**: the headless-Chrome job is the
only flaky stage in the pipeline (see the media-upload timing fixes on 13–14 Jul), and gating production on a
flaky job trades a real failure mode (deploys blocked by test infrastructure) for a hypothetical one. The
functional coverage it would have caught is duplicated over real HTTP in `compose-e2e`, which *does* gate. The
cost is honest and stated: **a genuine front-end regression that only the browser job can see would reach
prod.** Tracked as an accepted risk in [`REPORT.md`](REPORT.md) §5.5.

**A deploy that failed for a non-pipeline reason** —
[run 29630794935](https://github.com/LiorBenSidi/work-smarter-not-harder/actions/runs/29630794935) · `main` · 2026-07-18 04:40 UTC.
Every gate green, `build` green, `deploy` red on
`ssh: connect to host sweng-group-02.eastus.cloudapp.azure.com port 22: Connection timed out`. Cause: the
course VM's **instructor-configured auto-shutdown** (23:50 UTC) — the run landed while the machine was off.
Prod was left on the previous good image rather than a half-applied one, and the next green `main` (19 Jul)
deployed cleanly. This is the operational risk behind the submission-day checklist item "confirm the VM is
running"; it is environmental, not a defect in the pipeline.

## Demo crib — one line per directive (the grader asks "why this?")

- `if: github.event_name == 'push'` — a PR runs tests only; it can never deploy (R1.3).
- `needs: checks` / `needs: build` — a red earlier stage means later stages never start (R2.2/R8.1).
- `${GITHUB_SHA::7}` tag — immutable per-commit provenance; `latest` is the stable pointer the VM pulls (R3.2).
- `--password-stdin` — keeps `GITHUB_TOKEN` out of the process list and logs (R4.2/R6.2).
- prod compose uses `image:` not `build:` — the VM runs the exact bits CI pushed; it never rebuilds (R5.2).
- `restart: unless-stopped` — the container comes back after a crash or VM reboot (R5.4).
- `curl --fail --retry-all-errors …/ready` — `/ready` pings Mongo (proves the whole stack, not just liveness); `--fail` → non-zero on any HTTP error; `--retry-all-errors` also rides out the cold-boot TLS handshake; targets the FQDN so it proves the VM, not the runner (R7).
- **auto-rollback** — the deploy records the last-good SHA; a failed `/ready` re-deploys it so prod is restored, while the run still ends red (R8.2).
- Caddy `reverse_proxy web:5000` — Caddy does ACME + renewal + HTTP→HTTPS automatically; gunicorn stays on plain HTTP behind it (R10, per the assignment's gunicorn note).
