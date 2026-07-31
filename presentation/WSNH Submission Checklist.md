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
      real inference. Remaining against "every proposal feature present": the **F5 workout-generator**
      (Shiri; F6 program-balance already ships as the merged F7 pipeline).)*
- [x] **AI Job Queue (+5)** — `ai/jobqueue.py` (bounded queue + process pool). ✅ built.
- [x] **Online Forum (+10)** — all 7 sub-features + real-time + anonymity bonus + **cold-seeding** ✅
      (`db/seed.py`: fake clients + posts + comments + likes — a deliberate demo/review tool; see below).
- [x] **Azure deploy + CI/CD (+10)** — live over HTTPS, auto-deploy + rollback. ✅ built & live.
- [x] **Report** — `docs/REPORT.md` (app overview · features×tests matrix · risk assessment). ✅ current
      (1063 tests). Submitted as the in-repo `.md` — the guidelines take a repo link, not a PDF.
- [ ] **Demo video** — record from `WSNH Demo Video Script.md`; name `VID_<id1>_<id2>_<id3>.mp4`.
- [ ] **Presentation** — **`WSNH Presentation (Canva).pptx/.pdf`** (8-slide light/projector deck, design `DAHO6FXsV5o`) + **`WSNH Speaker Script (8-slide Canva).md`** (word-for-word, 2 handoffs); rehearse to 5:00. *(`WSNH Presentation.pptx` + `WSNH Speaker Notes and QA.md` are the retired 11/12-slide versions — Q&A bank in the latter is still useful.)*

## Pre-submission checklist (do these before you submit)
**Must-fix (the visible gaps):**
- [x] **Shiri: land the trained Random Forest** → real `/predict` (F3), recommendation engine (F7), calories
      (F4) — **landed.** `ai/model/model.pkl` + `inference.py` are baked in and predictions are real (the old
      "every prediction reads Moderate" placeholder behaviour is gone). Still open on her lane: the **F5
      workout-generator / F6 program-balance** scope.
- [x] **Forum cold-seed content** — ✅ **built** (Lior): `db/seed.py` seeds fake clients + posts + comments
      + likes over a back-dated timeline. It's a **deliberate demo/review tool**, run by hand — a fresh
      database stays **empty by design**. **Before the review: run it once against the live prod DB** so the
      TA sees a populated app at `app.worksmarternotharder.dev` (see `db/README.md` for the exact command).
- [ ] **Add the "See It Live" demo slide** to the Canva deck (as slide 5, after Architecture) — pre-recorded 30–45s clip recommended over live for the 5-min cap. Optionally add app screenshots to slides 2–6.
- [x] **Lior + Elad: final timeout tune** — **done, no retune needed.** Measured against the real model,
      `AI_PREDICT_TIMEOUT_SECONDS`=30 / `AI_CLIENT_TIMEOUT`=33 already sit well clear of observed latency
      (`docs/SCALING_REPORT.md`).

**Verify (should already be true):**
- [x] Suite green — **1063 collected** (real-Mongo IT runs on the `mongo:7` CI service); `main` green.
- [x] Live URL serves over HTTPS; auto-deploy + rollback working.
- [x] No committed secrets; only `web` exposed; auth/CSRF/injection defenses in place (TA-reviewed clean).
- [x] Docs reconciled to reality (counts, ownership, deploy gate, data model).
- [ ] **Everyone has commits** — GitHub history is graded per member (course requirement); make sure each
      member's work lands as their own commits before submission.

**Belt-and-suspenders:**
- [ ] Make sure the **Azure VM is running** at demo/submission time (instructor auto-shutdown at 23:50 UTC —
      start it from the Azure portal beforehand; `DEPLOY_ENABLED=true`).
- [ ] Do one **fresh-clone run** (`cp .env.example .env && docker compose up --build`) to confirm it works from
      scratch, exactly as a TA would try it.
- [ ] Re-run the demo end-to-end once the model is in, so shot 3 shows a real prediction.

## The one-line status
Engineering is submission-ready and TA-reviewed clean; the AI model has landed and the forum cold-seed tool
is built (run it against prod before the review). The remaining items are the **F5 workout-generator**
(Shiri) and the **team deliverables** — the demo **video**, the rehearsal, and pasting the **repo link** into
the Moodle final-project box when it opens (format is settled: repo link + video + report, **no zip**).
