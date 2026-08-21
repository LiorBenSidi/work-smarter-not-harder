# Work Smarter, Not Harder — final submission checklist

**Team Git Push & Pray** — Shiri · Lior · Elad · IDs **<id1> · <id2> · <id3>**
**Naming convention:** `<id>_<id>_<id>` → **`<id1>_<id2>_<id3>`** for the demo **video** (`VID_<id1>_<id2>_<id3>.mp4`).
*(No project zip — the graded hand-in is a repo link; the only zip is the separate Show Off gallery, named after **one** member's ID.)*

> **Hand-in format** (per `docs/Proj_Guidelines.pdf` p11–12): submit **(1) the GitHub repo link — "no more
> zips"**, **(2) a video** of the app in use, and **(3) the report** (`docs/REPORT.md`). `README.md` must exist
> with run + test instructions; **−5 each time the code doesn't run**. So the report is the in-repo `.md` (no
> PDF needed) and there is **no project zip** — the only residual is confirming *which* Moodle box to paste the
> repo link into.

## Dates
| When | What |
|---|---|
| **Thu 16 Jul** | **Presentation — 5 minutes (mandatory).** 24 projects; **we're slot 8 @ 9:15**. Class vote *during* the presentations — **7-place bonus:** 1st **+10** · 2nd **+7** · 3rd **+5** · 4th **+4** · 5th **+3** · 6th **+2** · 7th **+1** (on the final-project grade). |
| **~Week 12** | **Working demo** to the TA (the live app / demo video). |
| **23 Aug** | **Final submission** — the complete project. |

**Penalties:** −5 per bug found · −5 per week late. So ship on time and land the fixes below.

## Deliverables (map to the rubric: 75 + 5 + 10 + 10)
- [ ] **The working app (75)** — the repo + the **live URL** (app.worksmarternotharder.dev). Runs on Docker.
      *(Shiri's Random Forest has landed — `ai/model/model.pkl` is baked into the image and `/predict` serves
      real inference. F5's AI generation is now built and wired into `/predict` too (catalog, split
      resolution, exercise selection). Remaining against "every proposal feature present": the dashboard
      doesn't relay or render the generated `plan` yet (web tier, #410; F6 program-balance already ships as
      the merged F7 pipeline).)*
- [x] **AI Job Queue (+5)** — `ai/jobqueue.py` (bounded queue + process pool). ✅ built.
- [x] **Online Forum (+10)** — all 7 sub-features + real-time + anonymity bonus + **cold-seeding** ✅
      (`db/seed.py`: fake clients + posts + comments + likes — a deliberate demo/review tool; see below).
- [x] **Azure deploy + CI/CD (+10)** — live over HTTPS, auto-deploy + rollback. ✅ built & live.
- [x] **Report** — `docs/REPORT.md` (app overview · features×tests matrix · risk assessment). ✅ current
      (1412 tests). Submitted as the in-repo `.md` — the guidelines take a repo link, not a PDF.
- [ ] **Demo video** — record from `WSNH Demo Video Script.md`; name `VID_<id1>_<id2>_<id3>.mp4`.
- [x] **Presentation** — *its slot was **Thu 16 Jul** and has passed; this is no longer pre-23-Aug work.* Deck: **`WSNH Presentation (Canva).pptx/.pdf`** (8-slide light/projector deck, design `DAHO6FXsV5o`) + **`WSNH Speaker Script (8-slide Canva).md`** (word-for-word, 2 handoffs); rehearse to 5:00. *(`WSNH Presentation.pptx` + `WSNH Speaker Notes and QA.md` are the retired 11/12-slide versions — Q&A bank in the latter is still useful.)*

## Pre-submission checklist (do these before you submit)
**Must-fix (the visible gaps):**
- [x] **Shiri: land the trained Random Forest** → real `/predict` (F3), recommendation engine (F7), calories
      (F4) — **landed.** `ai/model/model.pkl` + `inference.py` are baked in and predictions are real (the old
      "every prediction reads Moderate" placeholder behaviour is gone). **F5's AI side is also landed and
      wired into `/predict`** (catalog, split resolution, exercise selection). Still open: F6's `program`
      input (#276 P7, the generated plan isn't fed into `_program_recommendations` yet) and the dashboard
      relaying/rendering `plan` (#410, web tier).
- [x] **Forum cold-seed content** — ✅ **built** (Lior): `db/seed.py` seeds fake clients + posts + comments
      + likes over a back-dated timeline. It's a **deliberate demo/review tool**, run by hand — a fresh
      database stays **empty by design**. **Before the review: run it once against the live prod DB** so the
      TA sees a populated app at `app.worksmarternotharder.dev` (see `db/README.md` for the exact command).
- [x] **Add the "See It Live" demo slide** to the Canva deck — *moot: the 16 Jul presentation has passed. Kept for the record.*
- [x] **Lior + Elad: final timeout tune** — **done, no retune needed.** Measured against the real model,
      `AI_PREDICT_TIMEOUT_SECONDS`=30 / `AI_CLIENT_TIMEOUT`=33 already sit well clear of observed latency
      (`docs/SCALING_REPORT.md`).

**Verify (should already be true):**
- [x] Suite green — **1412 collected** (real-Mongo IT runs on the `mongo:7` CI service); `main` green.
- [x] Live URL serves over HTTPS; auto-deploy + rollback working.
- [x] No committed secrets; only `web` exposed; auth/CSRF/injection defenses in place (TA-reviewed clean).
- [x] Docs reconciled to reality (counts, ownership, deploy gate, data model).
- [ ] **Everyone has commits** — GitHub history is graded per member (course requirement); make sure each
      member's work lands as their own commits before submission.

**Operational:**
- [ ] **Freeze deploys during Noam's review window** — don't push to `main` or merge PRs while the TA is
      on the live site. A mid-review SW reload drops the user to the login screen (known; not worth a code
      fix given the 17-day window, but avoidable by not deploying).

**Belt-and-suspenders:**
- [ ] Make sure the **Azure VM is running** at demo/submission time (instructor auto-shutdown at 23:50 UTC —
      start it from the Azure portal beforehand; `DEPLOY_ENABLED=true`).
- [x] Do one **fresh-clone run** — **done 10 Aug, and it passes.** Cloned from GitHub into a new directory,
      `cp .env.example .env && docker compose up -d --build`, nothing else. All three containers came up
      **healthy**; only `web` published a host port (`8000→5000`) — `ai` and `db` bind nothing, so the
      isolation requirement holds on the reviewer's own machine. End to end: register → the verification
      code appears **on screen** (no SMTP configured → `email_mode: mock`) → verify 201 → login → the
      2-step code appears → 200 → check-in **201 with a real Random-Forest prediction** (`Ready`, live
      probabilities) → `/dashboard` 200 with recommendations. `./seed.sh` then filled the forum:
      **5 posts · 6 comments · 5 users**, and `coach_maya` / `demo-seed-pw` signs in.
      Two things to know rather than fix: the calorie target reads `null` until a **profile** is saved
      (readiness needs only the check-in — by design, #266), and a fresh forum is **empty until
      `./seed.sh` runs**, which README:109 already tells the reviewer. One environment note: the seed
      script cannot bind-mount a project kept under `/tmp` — it **detects that and prints the fix**;
      cloned under `$HOME`, as anyone would, it just works.
- [x] ~~Re-run the demo end-to-end once the model is in~~ — the model landed 11–12 Jul, so shot 3 is filmed in
      full. The only thing left here is the recording itself, tracked above.

## The one-line status
Engineering is submission-ready and TA-reviewed clean; the AI model has landed and the forum cold-seed tool
is built (run it against prod before the review). F5's AI generation has also landed, wired into `/predict`.
The remaining items are **F5's dashboard display** (web tier, #410 — relaying and rendering the generated
`plan`) and the **team deliverables** — the demo **video**, the rehearsal, and pasting the **repo link** into
the Moodle final-project box when it opens (format is settled: repo link + video + report, **no zip**).
