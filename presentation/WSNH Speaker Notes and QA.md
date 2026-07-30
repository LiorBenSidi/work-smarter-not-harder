# Work Smarter, Not Harder — speaker notes + TA Q&A prep

> ⚠️ **USE THE NEW SCRIPT FOR SPEAKING.** The per-slide speaker notes below are for the **old 12-slide layout** and are **superseded**. For the current **8-slide Canva deck** (`WSNH Presentation (Canva).pptx`, design `DAHO6FXsV5o`), read **[`WSNH Speaker Script (8-slide Canva).md`](WSNH%20Speaker%20Script%20%288-slide%20Canva%29.md)** — it has the 2-handoff blocks (Shiri 1–3 → Lior 4–6 → Elad 7–8), timed to 5:00.
>
> **What's still useful here:** the **Q&A bank** below (TA questions + answers) is deck-independent — keep using it. Only the per-slide "what to say" section is out of date.

Pair the **Q&A bank** below with the new speaker script and the deck. (The per-slide notes that follow reflect the retired 12-slide structure — kept for reference only.)

## Speaker notes (what to say, per slide)

1. **Title (Lior, 10s).** "We're Git Push & Pray. Our project decides, every morning, whether an athlete should
   push or rest — and it's **live** right now at app.worksmarternotharder.dev." *(Have the tab open.)* → hand to Shiri.
2. **Problem (Shiri, 40s).** "Athletes guess how recovered they are and end up overtraining or undertraining. We
   take a 30-second morning check-in — sleep, resting HR, soreness, load — and return **one** signal: Ready,
   Moderate, or Rest, with a recommendation and a calorie target. One decision, not another dashboard." → Lior.
3. **Architecture (Lior, 40s).** "Three Docker containers — web, ai, db. Only **web** is exposed; ai and db are
   internal. web talks to them over two fixed contracts: `/predict` and the db data API. It runs on an Azure VM,
   HTTPS via Caddy." → Shiri.
4. **AI brain (Shiri, 55s).** "A **local** Random Forest readiness classifier plus a recommendation engine and a
   Mifflin-St-Jeor calorie target. The model is baked into the ai image — no external API, no runtime download.
   It takes features and returns state, probabilities, and recommendations." *(If not final: "the pipeline is
   wired and returns valid shapes; the trained model drops into one seam, `predict_one`.")* → Elad.
5. **Job Queue +5 (Elad, 45s).** "`/predict` doesn't score inline — it enqueues onto a **bounded** queue worked
   by a **process** pool, so many users' predictions run in parallel. Past the bound it sheds a 503 instead of
   growing a backlog of work whose callers have already timed out — a bigger VM moves that cliff, it never
   removes it." → stay on Elad.
6. **Scaling (Elad, 30s).** "And it's measured: the pool one-to-four gives **2.86×** throughput; a second ai
   replica gives **1.60×**; the same test on a thread pool gives 0.96× — that's the GIL, and it's why we use
   processes." → Lior.
7. **Forum +10 (Lior, 50s).** "All seven forum sub-features: posts and comments with media, like/dislike with
   counts, direct messages, notifications, anti-abuse, and cold-seeding — everything **real-time**, no refresh,
   over server-sent events. Plus an anonymity toggle as a bonus." → stay on Lior.
8. **Security (Lior, 35s).** "It's built to be safe: password hashing, two-step login codes, email verification
   at signup, CSRF protection, injection-safe database queries — behind the whole data layer and Week-9 logging." → Lior.
9. **Testing (Lior, 30s).** "All five course test types — each one load-bearing, not padding. The invariants are guard-tested and
   **mutation-tested** — we broke each on purpose to prove the test catches it. Real-Mongo and cross-container
   tests run in CI and gate the build." → Elad.
10. **Deploy +10 (Elad, 45s).** "Every push runs the whole suite; on green it builds, pushes to a registry,
    SSH-deploys to Azure, serves HTTPS, health-checks, and **rolls back automatically** if the new version is
    unhealthy. That pipeline is what put the live URL up." → Lior.
11. **Close (Lior, 20s).** "Seventy-five plus five plus ten plus ten — a full app, the job queue, the forum, and
    a live CI/CD deploy, all tested and running. **Vote for us.**" *(End on the live URL.)*

---

## TA Q&A bank (anticipated questions → tight answers)

**Q: Why a *process* pool, not threads?**
Scoring is CPU-bound, and Python's GIL stops CPU-bound work from overlapping across threads. We measured it:
threads gave 0.96× (no gain), a process pool gave 2.86–3.58×. A guard test (`test_pool_scaling.py`) fails if
anyone swaps it back to threads.

**Q: How does the rollback work?**
The deploy job records the last-good image SHA *before* deploying the new one (the exact commit CI built, not a
moving `:latest`). After `up -d` it health-checks `GET /ready` (which pings Mongo, so a pass means the whole
stack serves). If that fails, it rewrites `IMAGE_TAG` back to the previous SHA and redeploys — the VM returns to
the last working version. The run still ends **red** so we know, but the site self-heals.

**Q: Where's the security?**
Werkzeug password hashing; two-factor login (password → one-time code); email verification at signup so you
can't register a fake or someone else's address; CSRF double-submit tokens; string-typed, injection-safe Mongo
queries; user-enumeration defenses (identical failure responses, a timing decoy hash); single-use signed reset
tokens; only `web` is exposed; secrets come from GitHub secrets at deploy time (nothing committed); HTTPS via
Let's Encrypt.

**Q: Why a *bounded* queue? What happens when it's full?**
An unbounded backlog under a flood fails twice: memory grows without limit, and the pool keeps scoring jobs
whose callers already timed out — pure waste. Bounded, it sheds a 503, which `web` already treats as
"ai unavailable" and degrades gracefully. Load-shedding, not falling over. (A bigger VM moves the memory
cliff; it never makes the queue bounded.)

**Q: Why only one gunicorn worker on the ai container?**
The job store is in-memory and per-process. A second worker would own a second store, so `GET /jobs/<id>` would
404 about half the time. Threads accept concurrent requests; the parallelism comes from the process pool.

**Q: What if a pool worker *dies* — or *hangs*?**
Both handled, both tested. A dead worker normally breaks a `ProcessPoolExecutor` **permanently** — every later
submit raises. Our queue **self-heals**: it detects the broken pool, replaces it (generation-guarded, so
concurrent detections rebuild once), retries the submit, and answers the one lost caller with a retryable 503.
A *hung* worker is reaped by a hard wall-clock deadline — its queue slot is reclaimed so hangs can't eat the
queue, and a fully-hung pool is replaced outright. Rebuilds are visible in `/queue/stats`, and both defences
were mutation-tested (disable the fix → the tests go red).

**Q: What happens if the ai container is down?**
`web` wraps the call in try/except with a timeout; on failure it returns None and the dashboard renders with
`ai_status: unavailable`. `web` even boots if ai is down. We test this by stopping the real ai container
(`test_fault_isolation.py`) — `/health` stays 200, the app degrades, it doesn't crash.

**Q: Is the model real / how accurate is it?**
*(Honest answer.)* The full pipeline is wired and the `/predict` contract is fixed; the trained Random Forest
drops into one seam (`ai/inference.py:predict_one`). *[If trained by demo day: give the accuracy + classes. If
not: say the model is the last piece and show the pipeline returning a readiness signal.]*

**Q: How is it "scalable via parallelization"?**
Two multiplying axes: the process pool inside one container (vertical, 2.86×) and `--scale ai=N` replicas
(horizontal, 1.60× for two). Both measured against a CPU-bound workload, not the microsecond placeholder.

**Q: What are the five test types and how many tests?**
Unit (279), integration (325), system (13), stress (12), security (91) — **720** total. The count is not the point: each is a real assertion, guard- and **mutation-tested** (disable the check → the test goes red), not scaffolding. They run on every push;
real-Mongo and cross-container E2E gate the build.

**Q: How does CI/CD gate a bad change?**
`build` needs both `checks` (lint + security + the full suite) **and** `compose-e2e` (the real 3-container stack
over HTTP). A broken wire path can't reach the registry or the deploy — it fails the PR instead.

**Q: What's the data model?**
MongoDB collections: `users`, `profiles`, `analysis_history`, `forum_posts`, `messages`, `notifications`,
`media`. Indexed, with `$jsonSchema` validators.

**Q: What did each person build?**
Shiri: the AI model + recommendation engine + cold-seed content. Lior: the web app, the whole data layer, auth
+ security, the forum real-time layer (DM, notifications), logging, containers, and the CI/CD pipeline. Elad: the
live Azure deploy, the job queue + scaling, forum media, and the stress/cross-container tests.

**Q: Why is the anonymity toggle a "bonus"?**
The updated TA guidelines don't list it as a requirement, but we'd already built it, so it's a retained bonus —
not counted against the seven required sub-features.

**Q: Is `/predict` replica-safe under `--scale ai=2`?**
Yes — `POST /predict` is replica-safe and it's all `web` calls. `GET /jobs/<id>` is *not* (per-container store),
so we deliberately don't wire `web` to it; documented and guard-tested.

**Q: How do you stop huge-file uploads / spam?**
Per-upload size caps + MIME checks reject an oversized body before Flask parses it; `flask-limiter` rate-limits
the public write routes. Both covered by security tests.
