# Presentation kit — "Work Smarter, Not Harder"

Everything for the **final-project presentation**, in one place all three of us can find and edit.

- 🟢 **Live app:** https://app.worksmarternotharder.dev
- 🎨 **Slides (Canva master — click to edit):** https://canva.link/50e4i8nxkaslrbj  *(team edit link; opens design `DAHO6FXsV5o`)*
- 📄 **Deck (view/offline):** [`WSNH Presentation (Canva).pdf`](WSNH%20Presentation%20%28Canva%29.pdf) — 8 slides, projector-ready, scan-to-try QR on slides 1 & 8.

## 📅 Presentation — Thursday 16 July 2026
- **5 minutes, mandatory.** 24 projects; **we're slot 8 @ 9:15** (presenters Lior · Elad · Shiri).
- **Class vote during the presentations → 7-place bonus** on the grade: 1st +10 · 2nd +7 · 3rd +5 · 4th +4 · 5th +3 · 6th +2 · 7th +1.

## Files here — what each is
| File | What it is | Use for |
|---|---|---|
| [`WSNH Speaker Script (8-slide Canva).md`](WSNH%20Speaker%20Script%20%288-slide%20Canva%29.md) | **Word-for-word script**, per slide, timed 5:00, 2 handoffs | Rehearse your lines |
| [`WSNH Canva Notes (paste per slide).md`](WSNH%20Canva%20Notes%20%28paste%20per%20slide%29.md) | Same notes, formatted to paste into Canva's Notes panel | Reference / re-paste |
| [`WSNH TA Mock QA Drill.md`](WSNH%20TA%20Mock%20QA%20Drill.md) | Hard TA questions + crisp answers | Q&A practice |
| [`WSNH Speaker Notes and QA.md`](WSNH%20Speaker%20Notes%20and%20QA.md) | ⚠️ *old 12-slide notes (superseded)* — its **Q&A bank** is still current | Q&A bank only |
| [`WSNH Demo Video Script.md`](WSNH%20Demo%20Video%20Script.md) | Shot-list for the 3–5 min submission demo video | Record the full video |
| [`Demo clip - recording checklist.md`](Demo%20clip%20-%20recording%20checklist.md) | Tight checklist for the **30–45s slide-5 clip** (pre-flight, 4 shots, settings) | Record the presentation clip |
| [`WSNH Submission Checklist.md`](WSNH%20Submission%20Checklist.md) | Dates, deliverables, pre-submission must-fixes | Don't miss anything |
| [`WSNH Presentation Outline.md`](WSNH%20Presentation%20Outline.md) | Timing map + delivery notes | Big-picture timing |
| [`scan-to-try-QR.png`](scan-to-try-QR.png) | Standalone QR → the live app | Posters / sharing |
| [`For Elad - job queue robustness.md`](For%20Elad%20-%20job%20queue%20robustness.md) | Notes for Elad on the AI job-queue robustness items | Elad's follow-ups |
| [`../ai/For Shiri - predict contract.md`](../ai/For%20Shiri%20-%20predict%20contract.md) | **Zero-rework spec for Shiri's model** — exact `/predict` shape + training plan (lives next to `ai/inference.py`) | Plug the model in |

**How they connect:** the **Canva design is the master** — edit there, then **File → Download** the PPTX/PDF to refresh the deck. The **Speaker Script** is *what to say*; the **Canva Notes** file is the same text pasted into Canva's per-slide notes.

## Who presents what (only 2 handoffs)
- **Shiri** → slides **1–3** (Title · Product · AI brain)
- **Lior** → slides **4–6** (Architecture · Forum · Security & testing)
- **Elad** → slides **7–8** (Scaling · Deploy + the ask)

Handoffs: end of slide 3 → Lior, end of slide 6 → Elad.

## Left to do
- **AI (Shiri):** **F5 workout generator** + forum cold-seed content. *(The Random Forest classifier is built and live behind a real `/predict` — the "reads Moderate" placeholder era is over; F5 is the remaining AI feature.)* **Spec:** [`../ai/For Shiri - predict contract.md`](../ai/For%20Shiri%20-%20predict%20contract.md).
- **Team:** add the **"See It Live"** demo slide (as slide 5 in Canva, after Architecture) + record the 30–45s clip; do one **timed rehearsal**.

## Editing the deck (Shiri & Elad)
Open the **Canva master** link above — it's a team edit link, so you can edit directly (no invite needed). Edit in Canva (source of truth), then re-download the PPTX/PDF to refresh the deck. Presenter notes live in Canva **and** in the exported PPTX — re-exporting overwrites the PPTX, so re-paste from `WSNH Canva Notes (paste per slide).md` if needed.

---
*The app itself is documented in the repo root [`README.md`](../README.md) and [`docs/`](../docs). All three members commit their own work (course requirement).*
