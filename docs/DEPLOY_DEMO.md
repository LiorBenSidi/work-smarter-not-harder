# Deploy demo — run-sheet, UptimeRobot setup & grader Q&A

Everything needed to run the CI/CD live demo (assignment §7, acceptance **A–I**) and answer the grader's
questions. Pipeline detail + the R1–R10 mapping live in [`CICD_REPORT.md`](CICD_REPORT.md); the setup steps are
in the [README](../README.md#deployment-cicd--azure). This file is the **run-sheet** for demo day.

`SITE` below = your public HTTPS host: `app.worksmarternotharder.dev` (custom domain) or the Azure FQDN.

---

## 0 · Pre-demo checklist (every box must be ✓)
- [ ] GH **secrets** `SSH_PRIVATE_KEY`, `APP_SECRET_KEY` set; **variables** `SSH_HOST` (the FQDN) **and `DEPLOY_ENABLED`
      = `true`** (the deploy on/off switch — leave `false`/unset to keep `main` green during dev) — and, for the custom
      domain, `SITE_ADDRESS` = `app.worksmarternotharder.dev`. *(Email: optional `SMTP_USER`/`SMTP_PASS`.)*
- [ ] The deploy key's `.pub` is on the VM's `azureuser` account (sent to the instructor; `azureuser` replaced the old `deploy` name).
- [ ] Name.com: `CNAME app → <the FQDN>` added (only if using the custom domain).
- [x] Both GHCR packages **public** (`work-smarter-web`, `work-smarter-ai`). ✅ done.
- [ ] The VM is **started** (Azure portal → your VM → Start — idle VMs auto-stop).
- [ ] **A green deploy has run at least once** before the demo, so the Let's Encrypt cert is issued and
      `~/app/.last_good_sha` exists (the rollback anchor). Don't let the *first-ever* deploy be the live demo.
- [ ] UptimeRobot monitor is live (§1) and has at least one recorded **down→up** event.
- [ ] `curl https://$SITE/ready` returns `200` with a valid padlock (no `-k`).

---

## 1 · UptimeRobot setup (R9) — do once, well before the demo
1. Create a **free** account at uptimerobot.com (free tier = **5-minute** interval, which satisfies R9.1's "≤ 5 min").
2. **+ Add New Monitor:**
   - Monitor Type: **HTTP(s)**
   - Friendly Name: **Work Smarter — /ready**
   - URL: **`https://<SITE>/ready`**
   - Monitoring Interval: **5 minutes**
3. **Alert Contacts:** add your **email** so DOWN and UP both notify you (R9.3).
4. Save. It's a third-party service, independent of the VM (R9.2), polling the public HTTPS endpoint (R9.1).

Why `/ready` and not `/health`: `/ready` pings Mongo, so the monitor also catches a DB outage, not just the box
being down. If you'd prefer a pure "is the site up" monitor with fewer false alarms on a DB blip, point it at
`/health` instead — either satisfies R9.

---

## 2 · Live-demo run-sheet (acceptance A–I, in order)

**A + B — a visible change auto-deploys, no manual step.**
Pick a string **no test pins** (see the ⚠️ below), commit, push to `main`:
```bash
# safe target: add/bump a field on /ready (tests only assert its "status" key).
# in web/app.py, /ready success branch:  return jsonify(status="ready", db="up", version="demo-2"), 200
git commit -am "demo: bump /ready version string" && git push
```
GitHub → **Actions** → watch `checks → build → deploy` run end-to-end with **no manual intervention** (B).
> ⚠️ Do **not** edit `/health`'s body for the demo — `tests/Integration_Tests/test_web_smoke.py` and
> `test_auth_flow.py` assert it exactly (`{"status":"ok","service":"web"}`). If you want to change `/health`,
> update those two tests in the **same commit** so `checks` stays green.

**C — the SHA image is in GHCR.** Show `github.com/users/LiorBenSidi/packages` → `work-smarter-web` → the new
tag equals the commit's short SHA (C).

**D — the VM serves the change over HTTPS.** After the run is green (the grader runs this — no `-k`):
```bash
curl https://$SITE/ready        # shows version="demo-2", valid Let's Encrypt cert
```

**E — the health check passed.** In the green `deploy` job, point at the **"Health check … /ready"** step (E).

**F — a broken PR does NOT deploy.** Open a PR that breaks a test:
```bash
git checkout -b demo/break-a-test
# add a failing assertion in any test, e.g.  assert 1 == 2
git commit -am "demo: intentionally break a test" && git push -u origin demo/break-a-test
gh pr create --fill
```
Show the PR checks: **`checks` ❌ red**, and **`build` + `deploy` skipped** — nothing deployed (F). Close the PR after.

**G — no secrets exposed.**
```bash
git grep -InE "SECRET_KEY=|SMTP_PASS=|BEGIN [A-Z ]*PRIVATE KEY" -- . ':!*.example'   # → nothing
```
Open any `deploy` run's logs → secret values render as `***` (GitHub masking). SSH password login is **off** on
the VM (instructor's cloud-init, R6.3); we use a dedicated deploy key, not a personal one (G).

**H — the monitor's down→up.** Trigger it live:
```bash
ssh -i ~/.ssh/deploy_key azureuser@$SSH_HOST "cd ~/app && docker compose -f docker-compose.prod.yml stop web"
#   → within one interval UptimeRobot flips DOWN + emails you
ssh -i ~/.ssh/deploy_key azureuser@$SSH_HOST "cd ~/app && docker compose -f docker-compose.prod.yml start web"
#   → it recovers to UP
```
Show the UptimeRobot status page + the alert email (H).

**I — valid, auto-renewing HTTPS.** Browser padlock at `https://$SITE` (valid, no warning), plus:
```bash
curl -sI http://$SITE | grep -i location        # 301/308 → https (HTTP redirects, R10.4)
echo | openssl s_client -connect $SITE:443 -servername $SITE 2>/dev/null | openssl x509 -noout -issuer
#   issuer = ... Let's Encrypt ...   (publicly trusted, not self-signed)
```
Renewal is automatic (Caddy); the cert + ACME account persist in the `caddy-data` volume, so restarts don't
re-issue (I).

**Evidence to capture** (assignment §6.4): the link to this successful `main` run, and the link to the failing PR
run from step F.

---

## 3 · Grader Q&A — "why did you do X?"
The assignment note is explicit: AI-generated-without-understanding fails at the demo. Know these cold.

- **Why `--retry-all-errors` on the health curl?** — `--fail` exits non-zero on any 4xx/5xx, but on the *first*
  deploy Caddy is still getting the cert, so the request fails at the **TLS handshake** — not connection-refused
  or a 5xx. `--retry-connrefused` wouldn't retry that; `--retry-all-errors` does. It stops a healthy first deploy
  from going red.
- **Show a failing PR — what stopped the deploy?** — the broken test fails `checks`; `build` has `needs: checks`
  so it never runs, and `build`/`deploy` are gated `if: github.event_name == 'push'`, so a PR can't deploy at all.
- **Prove no secret is in the repo / image / logs.** — secrets go in via `env:` and `--password-stdin` (never on
  a command line); GitHub masks them as `***`; `.env`, `prod.env`, and the deploy key are gitignored. The image is
  built from a clean checkout (no gitignored `.env`) with a `web/.dockerignore`, and `config.py` reads every secret
  from `os.environ` — nothing hardcoded.
- **Why does the VM pull the image instead of building it?** — R5.2: the VM runs the **exact** SHA image CI built
  and pushed, so runner and prod are bit-identical; faster, reproducible, and the VM needs no build toolchain.
- **Why two tags, `latest` and the short SHA?** — the SHA is an immutable per-commit tag (provenance + the
  rollback anchor); `latest` is the stable pointer the compose file tracks by default.
- **What happens if a deploy is unhealthy?** — the deploy records the last-good SHA on the VM; a failed `/ready`
  check re-deploys that SHA (auto-rollback, R8.2). The run still ends **red**, so the failure isn't hidden.
- **Why Caddy, not nginx + certbot?** — Caddy obtains, installs, and auto-renews the Let's Encrypt cert and does
  HTTP→HTTPS with a two-line config; TLS automation isn't the learning goal, so it removes a class of bugs.
  gunicorn stays on plain HTTP behind it (its own docs warn against terminating TLS directly).
- **How is the cert renewed?** — Caddy renews automatically before expiry; the cert + ACME account live in the
  `caddy-data` volume, so a restart never triggers a re-issue storm.
- **Why hit the FQDN in the health check, not `localhost`?** — R7.2: it must prove the **deployed** server over the
  real public HTTPS path, not a container on the CI runner.
- **`/health` vs `/ready`?** — `/health` is trivial liveness (200 without touching Mongo — it must boot before the
  DB layer); `/ready` pings Mongo and 503s if it's down. The container healthcheck uses `/health`; the deploy gate
  and the monitor use `/ready`, so "green" means the whole stack serves.
- **Where is SSH password login disabled?** — the instructor's cloud-init sets `PasswordAuthentication no` (R6.3),
  key-only. The grader verifies it on the VM.
