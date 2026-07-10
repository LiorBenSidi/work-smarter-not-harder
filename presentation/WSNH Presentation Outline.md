# Work Smarter, Not Harder — 5-minute presentation outline

**Team Git Push & Pray:** Shiri (AI) · Lior (web + data + CI/CD) · Elad (deploy + scale + queue + forum-media)
**Live:** https://app.worksmarternotharder.dev
**When:** **Thu 16.07** — mandatory. 24 projects present; **we are slot 8 @ 9:15** (presenters Lior · Elad · Shiri). Class votes *during* the presentations.
**Rubric being demonstrated:** 75 (build) · +5 (Job Queue) · +10 (Forum) · +10 (Azure + CI/CD). −5 per bug.
**Bonus (7 places, on the final-project grade):** 1st **+10** · 2nd **+7** · 3rd **+5** · 4th **+4** · 5th **+3** · 6th **+2** · 7th **+1**. So the deck must *sell* it, not just report it.

> 🎤 **The live deck is the 8-slide Canva deck** — `WSNH Presentation (Canva).pptx` (design `DAHO6FXsV5o`). The timing map below now matches it. For the **word-for-word spoken script**, read **[`WSNH Speaker Script (8-slide Canva).md`](WSNH%20Speaker%20Script%20%288-slide%20Canva%29.md)**. *(The older 11-slide matplotlib deck `WSNH Presentation.pptx` is kept only as a fallback.)*

> ⚠️ **Before the day:** slide 3 (the AI brain) assumes Shiri's Random Forest is trained by 16 Jul. If it's still the
> placeholder, present slide 3 as the **design + the working pipeline** (the `/predict` seam returns real
> `{state, proba, recommendations}` shapes today) and don't claim an accuracy number. Everything else is live now.

## Timing map (5:00) — 8-slide Canva deck, only 2 handoffs (Shiri → Lior → Elad)

| # | Slide | Presenter | ~sec | The one thing to land |
|---|---|---|---|---|
| 1 | Work Smarter, Not Harder (title + QR) | **Shiri** | 20 | "It's **live** right now — scan the QR and try it." |
| 2 | Push Today or Recover? | Shiri | 45 | One calm morning signal: **Ready / Moderate / Rest** + a plan. |
| 3 | A Local AI Brain | Shiri | 40 | A **local** Random Forest, **no external API**, baked into the image. |
| 4 | Architecture Overview | **Lior** | 40 | 3 containers, **only `web` exposed**, live on Azure over HTTPS. |
| 5 | Online Forum (+10) | Lior | 35 | All **7** sub-features + **real-time** (no refresh) + anonymity. |
| 6 | Security, Data & Testing | Lior | 35 | Hashing · 2FA · CSRF · injection-safe Mongo · 5 test types, mutation-tested + E2E gate. |
| 7 | AI Job Queue & Scaling (+5) | **Elad** | 40 | Bounded queue + **process pool**; **2.86×** & **1.60×** measured. |
| 8 | Commit to Live (+10) | Elad | 45 | Pipeline + rollback; **75+5+10+10**; scan the QR — **vote for us**. |

Total ≈ 5:00 (300s). **Two handoffs only:** end of slide 3 → Lior, end of slide 6 → Elad. Practice once with a timer; usual overrun = slides 2, 4, 7 — keep to the one point. It's a **hard 5-minute cap** (24 projects back-to-back), so an overrun eats your own close.

> **Optional demo slide:** insert **"See It Live"** as slide 5 (after Architecture); if you do, trim ~30s from slides 2/4/7. Pre-recorded 30–45s clip recommended over live for the 5-min cap (see `WSNH Demo Video Script.md`).

### The per-slide talking points below are for the RETIRED 11-slide deck — kept for reference. Use `WSNH Speaker Script (8-slide Canva).md` for the current deck.

## Talking points per slide

**1 — Title (Lior).** Name, team, and open the live URL in a browser tab *now* so the demo is one click away.
"Work Smarter, Not Harder decides, every morning, whether you should push or rest — and it's live."

**2 — Problem & product (Shiri).** Athletes overtrain or undertrain because "how recovered am I?" is a guess.
We turn profile + recovery metrics (sleep, resting HR, soreness, load) into **one** readiness signal + a plan +
a calorie target. Not "another dashboard" — one decision each morning.

**3 — Architecture (Lior).** Three Docker containers: `web` (Flask — the only one with a host port), `ai`
(the model, internal), `db` (MongoDB, internal). `web` orchestrates the other two behind two fixed contracts
(`/predict`, the `db.py` data API). Live on an Azure VM, HTTPS via Caddy + Let's Encrypt.

**4 — AI brain (Shiri).** A **local** Random Forest readiness classifier + a recommendation engine — trained
on wellness data, **baked into the `ai` image** (no external API, no runtime download). `features → {state,
proba, recommendations}` + a Mifflin–St-Jeor calorie target. *(If the model isn't final: present this as the
design + the pipeline that's already wired and returning valid shapes.)*

**5 — Job Queue +5 (Elad).** `/predict` doesn't score inline — it enqueues onto a **bounded** queue worked by
a **`ProcessPoolExecutor`** (a *process* pool, because the GIL blocks CPU-bound threads). Past the bound it
**sheds with 503** rather than growing a backlog of work whose callers already gave up. One gunicorn worker (the store is
in-memory); the parallelism is the pool.

**6 — Scaling (Elad).** Measured, not asserted: the pool 1→4 = **2.86×** throughput (p95 halved); `--scale
ai=2` = **1.60×**; the same test on a *thread* pool = **0.96×** — that's the GIL, and it's why the pool is
processes. Two multiplying axes.

**7 — Forum +10 (Lior).** All seven: posts (title/body/image/video) · comments (+media) · like/dislike with
counts + a personal total · **direct messages** (P2P + media) · **notifications** (DMs + who liked your
content) · **anti-abuse** (rate-limits + file-size caps) · **cold-seeding**. Plus **real-time** everywhere via
SSE (no manual refresh), retrievable chat history, and an **anonymity toggle** (retained bonus).

**8 — Web · data · security (Lior).** Werkzeug password hashing · **2-step login OTP** · email verification at
signup · CSRF double-submit · injection-safe Mongo queries · sessions. Behind it: the **whole data layer** —
`db.py` CRUD, Mongo indexes, `$jsonSchema` validators, backups, seed. Plus Week-9 observability (named
loggers, rotating-file handler, per-request access log).

**9 — Testing (Lior).** All **five** course types (unit · integration · system · stress · security) — each one load-bearing. The invariants that matter are **guard-tested and mutation-tested** (we broke each on purpose to prove
the guard fails). Real-Mongo integration + a **cross-container E2E** run in CI and **gate the build**.

**10 — Deploy + CI/CD +10 (Elad).** Every push runs ruff → bandit → pytest → the cross-container E2E; on green
it **builds + pushes to GHCR → SSH-deploys to the Azure VM → Caddy serves HTTPS**, then a **`/ready` health
gate** with **automatic rollback** if the new version is unhealthy. It's the pipeline that put the live URL up.

**11 — Close (Lior).** "75 + 5 + 10 + 10 — a full app, the job queue, the forum, and a live CI/CD deploy, all
tested and running at app.worksmarternotharder.dev. **Vote for us.**" End on the live URL.

## Delivery notes
- **Rehearse the handoffs** (Lior→Shiri→Lior→Shiri→Elad→…). The switches cost the most time; name the next
  speaker at the end of your slide.
- **Have the app open and logged in** before you start — if the live demo is part of the 5 min, it must be one
  click, not a login dance. Or run the pre-recorded demo video (see the demo shot-list).
- **Lead with "it's live."** A running URL beats any slide.

## Placeholders to fill before presenting (working copy)
The deck (`WSNH Presentation.pptx/.pdf`) marks each of these in **amber** — fill them in and delete the marker
before the real run:
- **Slide 4 (AI):** ☐ Shiri — trained model + accuracy · real readiness classes · a live prediction. *(today
  `/predict` is the wired placeholder)*
- **Slide 7 (Forum):** ☐ Shiri — the forum cold-seed content.
- **Slide 11 "Where we are — what's left":** the entire **REMAINING** column is a live status list (Shiri's
  model + cold-seed + predict-time/RAM · Lior+Elad timeout tune · team demo video + screenshots + rehearsal).
  Keep this slide only if you want to *show* status; otherwise cut it right before presenting.
- **Screenshots** (amber "add screenshot" notes): slide 2 (readiness ring) · slide 3 (3-container diagram) ·
  slide 4 (a prediction) · slide 7 (forum + a live DM/notification).
- **Demo video:** not recorded yet — see `WSNH Demo Video Script.md`.
