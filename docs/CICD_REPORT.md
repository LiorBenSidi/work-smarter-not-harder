# CI/CD Report — Work Smarter, Not Harder

Maps the CI/CD assignment requirements (R1–R10) to where and how this repository satisfies them.
Pipeline: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) · Prod stack:
[`docker-compose.prod.yml`](../docker-compose.prod.yml) · TLS: [`Caddyfile`](../Caddyfile).

**The app & its health endpoint.** *Work Smarter, Not Harder* is a 3-container Flask app (web + internal `ai`
inference + MongoDB). Only `web` is public. It exposes `GET /health` ([`web/app.py`](../web/app.py)) returning
`200 {"status":"ok"}`, used by the container healthcheck, the pipeline's post-deploy check (R7), and the external
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
| **R5.1** deploy over SSH after a successful push | `deploy` job: `ssh deploy@$SSH_HOST` | `deploy` job |
| **R5.2** VM **pulls** the image, never builds | `docker compose -f docker-compose.prod.yml pull && up -d`; prod compose uses `image:`, no `build:` | `deploy` job, `docker-compose.prod.yml` |
| **R5.3** idempotent redeploy | `pull && up -d` converges to the same state | `deploy` job |
| **R5.4** survives a VM reboot | `restart: unless-stopped` on every service | `docker-compose.prod.yml` |
| **R6.1** secrets as GitHub Actions secrets, injected at runtime | `SSH_PRIVATE_KEY`, `APP_SECRET_KEY` (secrets); `SSH_HOST` (variable) | repo settings, `deploy` job |
| **R6.2** no secret in repo/image/logs | `.env`, `prod.env`, `*_deploy` gitignored; key written to a file, GitHub masks secret values | `.gitignore`, `deploy` job |
| **R6.3** VM: key-only SSH | enforced by the instructor's cloud-init (verified by grader) | (instructor) |
| **R7.1/7.2** post-deploy health check on the deployed server | `curl --fail --retry-connrefused https://$SSH_HOST/health` | `deploy` job |
| **R8.1** any stage failing fails the whole run | `needs:` chain + default fail-fast | `ci.yml` |
| **R8.2** *(optional)* rollback on failed health check | not implemented (documented gap) | — |
| **R9** external uptime monitor, ≤5 min, alert, down→up | UptimeRobot on `https://<FQDN>/health` (browser setup) | README / live |
| **R10.1–10.5** valid auto-renewing Let's Encrypt HTTPS at the FQDN; HTTP→HTTPS | `caddy` service + `Caddyfile` (`reverse_proxy web:5000`); gunicorn stays internal | `docker-compose.prod.yml`, `Caddyfile` |

## What is live now vs. what activates with the VM

- **Live on the next push to `main` (no external setup):** `checks` → `build` → **GHCR push** (R1–R4). GHCR needs only
  the repo's own `GITHUB_TOKEN`, so R3/R4 are demonstrable immediately.
- **Dormant until the VM is provisioned:** the `deploy` job is **skipped** while the `SSH_HOST` variable is unset
  (keeps `main` green), and activates automatically once the VM FQDN + `SSH_PRIVATE_KEY` + `APP_SECRET_KEY` are set.
  R5, R7, R9, R10 then go live with no code change.

## Documented gaps / not yet done

- **R8.2 rollback** — not implemented (a failed health check fails the run but does not auto-revert to the previous
  image). Candidate follow-up: pin the previous SHA and re-`up` it on health failure.
- **R9 monitor** and the **first Let's Encrypt issuance (R10)** require the live VM and a browser step (UptimeRobot
  account), so they are configured at provisioning time, not in code.
- The **live demo** (push a visible change → watch it reach the VM; break a PR test; show the monitor's down→up) is
  performed at grading, per the assignment's acceptance criteria.

## Evidence (to attach after the first live runs)

- Successful pipeline run: _link a green `push`-to-`main` run._
- Failing run that blocked deploy: _link a PR whose test failed, showing `checks` red and `deploy` never started._

## Demo crib — one line per directive (the grader asks "why this?")

- `if: github.event_name == 'push'` — a PR runs tests only; it can never deploy (R1.3).
- `needs: checks` / `needs: build` — a red earlier stage means later stages never start (R2.2/R8.1).
- `${GITHUB_SHA::7}` tag — immutable per-commit provenance; `latest` is the stable pointer the VM pulls (R3.2).
- `--password-stdin` — keeps `GITHUB_TOKEN` out of the process list and logs (R4.2/R6.2).
- prod compose uses `image:` not `build:` — the VM runs the exact bits CI pushed; it never rebuilds (R5.2).
- `restart: unless-stopped` — the container comes back after a crash or VM reboot (R5.4).
- `curl --fail --retry-connrefused` — non-zero on any HTTP error; rides out container boot without an explicit sleep; targets the FQDN so it proves the VM, not the runner (R7).
- Caddy `reverse_proxy web:5000` — Caddy does ACME + renewal + HTTP→HTTPS automatically; gunicorn stays on plain HTTP behind it (R10, per the assignment's gunicorn note).
