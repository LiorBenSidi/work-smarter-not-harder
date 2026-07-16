# Reviewer notes — known limitations & by-design behaviours

For anyone grading or bug-hunting this system (TA / Noam). Its purpose is to separate **known,
intentional constraints** from **actual bugs**, so a documented limitation isn't logged as a defect. Every
item below is cross-linked to where it's built, tested, or discussed in detail.

The full **"what can go wrong"** analysis is [`REPORT.md` §5 — Risk assessment](REPORT.md); this page is
the short, reviewer-facing index plus the handful of behaviours a reviewer is most likely to *hit*.

## How grading runs (so the email caveat doesn't apply)

Per the TA's notes, the project is graded on the **backend, run locally via Docker** — deploying is not
required. To run and exercise everything, including the full auth flow, **without a mailbox**:

```bash
docker compose up --build -d        # web on http://localhost:8000
```

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
| **Uploading many media files** is not capped by count / total disk | Per-file size + MIME are capped, but there's **no per-user or total-storage cap yet** | ⚠️ known gap, tracked — [issue #313](https://github.com/LiorBenSidi/work-smarter-not-harder/issues/313) |
| **The live site is unreachable at night** | The Azure VM has a **nightly auto-shutdown** (cost control); it's started before it's needed | ⚠️ deploy-only, expected |
| **After a deploy, the old page shows until you reload** | The PWA service worker serves a cached shell, then updates on the next load | ⚠️ deploy-only, cosmetic |
| **A single-VM outage takes the whole live site down** | One VM, no redundancy — the course supplies one; containers are stateless so a second host is config, not a rewrite | 🟡 accepted risk — [REPORT §5.3](REPORT.md), [`DESIGN.md`](DESIGN.md) |

## Deeper reading

- [`REPORT.md` §5](REPORT.md) — the full, test-backed risk assessment (dependency failure, AI queue, scale/deploy, abuse/security).
- [`HARDENING_REVIEW.md`](HARDENING_REVIEW.md) — three independent adversarial reviews (no auth bypass / XSS / injection / crash found).
- [`EMAIL_DELIVERABILITY.md`](EMAIL_DELIVERABILITY.md) — the email investigation + the OTP-reuse fix.
- [`AUTH_TESTING.md`](AUTH_TESTING.md) — exercise register / 2-step login / reset locally with no mailbox.
- [`SCALING_REPORT.md`](SCALING_REPORT.md) — measured parallel-scaling numbers.
