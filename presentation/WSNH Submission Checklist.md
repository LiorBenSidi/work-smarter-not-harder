# Work Smarter, Not Harder — final submission checklist

**Team Git Push & Pray** — Shiri · Lior · Elad · IDs **<id1> · <id2> · <id3>**
**Naming convention:** `<id>_<id>_<id>` → **`<id1>_<id2>_<id3>`** (used for the zip + video, e.g.
`WSNH_<id1>_<id2>_<id3>.zip`, `VID_<id1>_<id2>_<id3>.mp4`).

> ⚠️ **Confirm the exact submission mechanics with the TA** (Moodle upload vs. repo link vs. zip; whether the
> report is a PDF or the live `docs/REPORT.md`). The items below are the deliverables; the *format* is the one
> thing to verify — this course's mini-HWs used a `<ids>.zip` on Moodle.

## Dates
| When | What |
|---|---|
| **Thu 16 Jul** | **Presentation — 5 minutes (mandatory).** 24 projects; **we're slot 8 @ 9:15**. Class vote *during* the presentations — **7-place bonus:** 1st **+10** · 2nd **+7** · 3rd **+5** · 4th **+4** · 5th **+3** · 6th **+2** · 7th **+1** (on the final-project grade). |
| **~Week 12** | **Working demo** to the TA (the live app / demo video). |
| **23 Aug** | **Final submission** — the complete project. |

**Penalties:** −5 per bug found · −5 per week late. So ship on time and land the fixes below.

## Deliverables (map to the rubric: 75 + 5 + 10 + 10)
- [ ] **The working app (75)** — the repo + the **live URL** (app.worksmarternotharder.dev). Runs on Docker;
      every proposal feature present. *(Open gap: Shiri's real model — see below.)*
- [ ] **AI Job Queue (+5)** — `ai/jobqueue.py` (bounded queue + process pool). ✅ built.
- [ ] **Online Forum (+10)** — all 7 sub-features + real-time + anonymity bonus. ✅ built (cold-seed content pending — Shiri).
- [ ] **Azure deploy + CI/CD (+10)** — live over HTTPS, auto-deploy + rollback. ✅ built & live.
- [ ] **Report** — `docs/REPORT.md` (app overview · features×tests matrix · risk assessment). ✅ current
      (686 tests). Export to PDF if the TA wants a file.
- [ ] **Demo video** — record from `WSNH Demo Video Script.md`; name `VID_<id1>_<id2>_<id3>.mp4`.
- [ ] **Presentation** — **`WSNH Presentation (Canva).pptx/.pdf`** (8-slide light/projector deck, design `DAHO6FXsV5o`) + **`WSNH Speaker Script (8-slide Canva).md`** (word-for-word, 2 handoffs); rehearse to 5:00. *(`WSNH Presentation.pptx` + `WSNH Speaker Notes and QA.md` are the retired 11/12-slide versions — Q&A bank in the latter is still useful.)*

## Pre-submission checklist (do these before you submit)
**Must-fix (the visible gaps):**
- [ ] **Shiri: land the trained Random Forest** → real `/predict` (F3), recommendation engine (F5/F6/F7),
      calories (F4). This is the one thing a TA running the app will notice — every prediction is "Moderate"
      until it lands.
- [ ] **Shiri: forum cold-seed content** (pre-seeded clients + historical posts/comments).
- [ ] **Add the "See It Live" demo slide** to the Canva deck (as slide 5, after Architecture) — pre-recorded 30–45s clip recommended over live for the 5-min cap. Optionally add app screenshots to slides 2–6.
- [ ] **Lior + Elad: final timeout tune** — once Shiri reports predict-time, set `AI_PREDICT_TIMEOUT_SECONDS` /
      `AI_CLIENT_TIMEOUT_SECONDS` accordingly (env vars, no code change).

**Verify (should already be true):**
- [x] Suite green — **653 passing / 33 env-gated (686 collected)**; `main` green.
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
Engineering is submission-ready and TA-reviewed clean. The remaining items are **the AI model + forum cold-seed**
and the **team deliverables** (demo video, rehearsal).
