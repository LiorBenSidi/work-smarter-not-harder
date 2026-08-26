# Reviewer notes — known limitations & by-design behaviours

For anyone grading or bug-hunting this system (TA / Noam). Its purpose is to separate **known,
intentional constraints** from **actual bugs**, so a documented limitation isn't logged as a defect. Every
item below is cross-linked to where it's built, tested, or discussed in detail.

The full **"what can go wrong"** analysis is [`REPORT.md` §5 — Risk assessment](REPORT.md); this page is
the short, reviewer-facing index plus the handful of behaviours a reviewer is most likely to *hit*.

## ⚠️ Live site not responding? It's the nightly auto-shutdown — here's how to wake it

**Grading does not need the live site.** The project is graded on the **backend, run locally via Docker**
(`docker compose up --build` — see the next section); deploying is not required, so a sleeping VM blocks
**no** part of the grade.

The **live URL** (<https://app.worksmarternotharder.dev>) runs on a single Azure VM with an
**instructor-configured nightly auto-shutdown (~23:50 UTC, cost control)**. It does **not** auto-start. So if
you open the live site outside working hours and it times out, that is **expected, not a bug** — the VM is
simply deallocated.

**Bringing it up is one command, then a short wait** (the whole stack self-starts — no per-container steps):

```bash
az vm start -n sweng-group_02 -g SWENG-GROUP_02          # or: Azure portal → the VM → Start
# then wait ~3 minutes; the public URL answers 200 with a valid Let's Encrypt cert (no -k):
curl -s -o /dev/null -w '%{http_code}\n' https://app.worksmarternotharder.dev/ready    # → 200
```

**Who can run it:** starting the VM needs Azure access to **our** subscription ("DDS - 095219 (EA)"), which
the **grader does not have**. A team member does — **Lior** (portal access). **If you find the live site down
and want it running, contact the team**; otherwise grade locally, which needs nothing external.

## How grading runs (so the email caveat doesn't apply)

Per the TA's notes, the project is graded on the **backend, run locally via Docker** — deploying is not
required. To run and exercise everything, including the full auth flow, **without a mailbox**:

```bash
cp .env.example .env                # first run only
docker compose up --build -d        # web on http://localhost:8000
./seed.sh                           # THEN: fill the app with demo data (see below)
```

Or as a single command: **`./install.sh --seed`** does all three and leaves the stack attached.

**Please run `./seed.sh` (or `--seed`).** A brand-new database is **empty by design** — that is real
product behaviour, not a missing feature, and the team decided against seeding on every boot so
nothing mutates data underneath your own testing. Without it you get a login screen and an empty
dashboard. With it: **15 demo athletes**, up to **60 days of check-in history each** (scored by the
real model, not stubbed), a forum of **25 posts / 28 comments** with votes, Hebrew and English
message threads, notifications and image/video attachments. Log in as **`coach_maya`** with the demo
password **`demo-seed-pw`** — every seeded athlete uses the same one.

With **no SMTP configured** (the default), every OTP / password-reset **code and link is surfaced
on-screen and in the logs** — see [`AUTH_TESTING.md`](AUTH_TESTING.md). So the email-delivery limitation
below is a **live-deploy-only** concern and is **not on the graded path**. A `FLASK_DEBUG` flag and a
gated `?debug=1` tools panel are available for debug mode.

## Behaviours a reviewer might hit — and why they're not bugs

| What you might see | Why it happens | Verdict / where |
|---|---|---|
| **429 "you're doing that too fast"** when flooding login / register / forum / check-in | Per-IP rate limits are the **defence engaging**, exactly as stress-testing should trigger. Only a 5xx would be a failure | ✅ by design — `test_rate_limit.py`, [REPORT §5.4](REPORT.md) |
| **503 "queue full / ai unavailable"** under a prediction flood | The AI job queue is **bounded** and sheds load early; `web` degrades and still renders | ✅ by design — `test_queue_backpressure.py`, [REPORT §5.2](REPORT.md) |
| **Readiness score "jumps"** between bands for similar inputs | The model is deterministic; the 0–100 score is mapped **within** the predicted band (Rest/Moderate/Ready), so a borderline prediction can flip bands and move the number. Not randomness | ✅ by design — `readinessScore` in the SPA |
| **OTP email arrives minutes late / not at all under a burst** (live deploy only) | The live deploy uses a **free-tier SMTP relay (Brevo)** that can queue bursts and has a daily quota. The app degrades gracefully (the code stays valid); a rapid re-login now reuses one code | ⚠️ deploy-only, documented — [`EMAIL_DELIVERABILITY.md`](EMAIL_DELIVERABILITY.md), [REPORT §5.1](REPORT.md). **N/A when grading locally** (codes on-screen) |
| **Flooding media uploads** → 429, or 507 once storage is full | Per-file size + MIME caps, **plus** a 20/min upload rate-limit and a volume-wide disk cap (`MEDIA_MAX_TOTAL_BYTES`, 507 when full) | ✅ by design — [#313](https://github.com/LiorBenSidi/work-smarter-not-harder/issues/313) fixed in #321; `test_media`, `test_rate_limit` |
| **The live site is unreachable at night** | The Azure VM has a **nightly auto-shutdown** (~23:50 UTC, cost control) and does **not** auto-start; a team member starts it manually. See the wake-it note at the top for the one command + the ~3-min wait; grading is local, so this blocks nothing | ⚠️ deploy-only, expected |
| **After a deploy, the old page shows until you reload** | The PWA service worker serves a cached shell, then updates on the next load | ⚠️ deploy-only, cosmetic |
| **A single-VM outage takes the whole live site down** | One VM, no redundancy — the course supplies one; containers are stateless so a second host is config, not a rewrite | 🟡 accepted risk — [REPORT §5.3](REPORT.md), [`DESIGN.md`](DESIGN.md) |

## Deeper reading

- [`REPORT.md` §5](REPORT.md) — the full, test-backed risk assessment (dependency failure, AI queue, scale/deploy, abuse/security).
- [`HARDENING_REVIEW.md`](HARDENING_REVIEW.md) — three independent adversarial reviews (no auth bypass / XSS / injection / crash found).
- [`EMAIL_DELIVERABILITY.md`](EMAIL_DELIVERABILITY.md) — the email investigation + the OTP-reuse fix.
- [`AUTH_TESTING.md`](AUTH_TESTING.md) — exercise register / 2-step login / reset locally with no mailbox.
- [`SCALING_REPORT.md`](SCALING_REPORT.md) — measured parallel-scaling numbers.
