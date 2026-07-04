# Secrets & live email — local, server, and CI/CD

Where every secret lives, and how to get the app sending **real email** the way it does on Lior's machine —
locally, on the deployed server, and in CI/CD. **No secret is ever committed** (`.env` is gitignored; only
`.env.example` is in git).

## TL;DR — you almost never need secrets

`cp .env.example .env && docker compose up --build` gives you the **full app in mock mode**: every code
(login OTP · signup verification · password reset) is **shown on screen + written to the log**. That is what
teammates and grading use — **zero secrets, nothing to share.** You only need the values below to send *real*
email. (The full switch guide is [`docs/AUTH_TESTING.md`](docs/AUTH_TESTING.md).)

---

## 1. Local — send real email, exactly like Lior's machine

The single switch is **`SMTP_HOST`**. Add these five lines to your **local `.env`** (get the real values the
secure way — §2):

```
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USER=<brevo-login-email>
SMTP_PASS=<brevo-smtp-key>
MAIL_FROM=Work Smarter <no-reply@worksmarternotharder.dev>
```

Then `docker compose up --build` → `curl localhost:8000/auth/config` returns `"email_mode":"live"` and codes
go to the inbox instead of the screen. Delete `SMTP_HOST` → back to mock. Every other auth mode is a `.env`
var too (`OTP_ENABLED`, `REGISTER_VERIFY_EMAIL`, …) — flip it there, no code change.

> **Note (a real bug we hit):** keep a comma OUT of `MAIL_FROM`'s display name — `Work Smarter, Not Harder <…>`
> reads as an address *list* to SMTP and silently breaks the send. `Work Smarter <…>` is safe.

## 2. Sharing secrets safely with the team

**Never paste a secret into WhatsApp / email / a commit.** Pick one:

- **A shared password-manager vault** (Bitwarden is free) — Lior adds one "Work Smarter `.env`" item; you copy
  it into your local `.env`. Easiest to keep everyone in sync.
- **A one-time self-destructing note** (e.g. privnote) — Lior sends a link that destroys itself once you open it.
- **Your own free Brevo account** (~5 min, 300 mails/day) — *most* secure: no shared credential at all. The only
  difference is your sender address. Use this unless you specifically need to match Lior's sender.

Your `.env` never leaves your machine — it's gitignored.

## 3. Server + CI/CD — GitHub Actions secrets & variables

The pipeline ([`.github/workflows/ci.yml`](.github/workflows/ci.yml)) reads these. It **self-gates**: `checks`
(lint · security · tests) run on every PR; **build + deploy run only on push to `main`, and deploy stays
SKIPPED until the `SSH_HOST` variable is set** — so `main` stays green until the VM is ready, then the deploy
activates with no code change.

**Secrets** — *Settings → Secrets and variables → Actions → Secrets*:

| Secret | What | Needed for |
|---|---|---|
| `APP_SECRET_KEY` | Flask `SECRET_KEY` — any long random string | deploy |
| `SMTP_USER` | Brevo login email | real email on the server (optional) |
| `SMTP_PASS` | Brevo SMTP key | real email on the server — **its presence flips the server to live** |
| `SSH_PRIVATE_KEY` | the **dedicated** deploy key's private half (not a personal key) | deploy (SSH to the VM) |
| `GITHUB_TOKEN` | auto-provided by Actions | GHCR image push — nothing to set |

**Variables** — same page → *Variables*:

| Variable | What |
|---|---|
| `SSH_HOST` | the VM host to SSH to — **setting this activates the deploy job** |
| `SITE_ADDRESS` | public HTTPS FQDN for the TLS cert + health check (optional; falls back to `SSH_HOST`) |

Set them with the GitHub CLI — run from the repo; values are read locally, never committed:

```sh
R=LiorBenSidi/work-smarter-not-harder
gh secret   set APP_SECRET_KEY  -R "$R"                       # prompts for the value (paste it)
gh secret   set SMTP_USER       -R "$R"
gh secret   set SMTP_PASS       -R "$R"
gh secret   set SSH_PRIVATE_KEY -R "$R" < ~/.ssh/deploy_key   # from the deploy key file
gh variable set SSH_HOST        -R "$R" --body "your-vm.cloudapp.azure.com"
gh variable set SITE_ADDRESS    -R "$R" --body "app.worksmarternotharder.dev"
```

The deploy renders these into the VM's `.env` at deploy time (never committed). Real email on the server is
self-gating: `SMTP_PASS` present → live inbox delivery; absent → the safe log backend, and login still works.
Deploy detail: [`docs/CICD_REPORT.md`](docs/CICD_REPORT.md).

> Provisioning the VM + setting its GitHub secrets and running the deploy is the deployment lane
> ([`PERSON3.md`](PERSON3.md), Elad); this file is the reference for **what** to set and **where**.
