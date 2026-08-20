# Submission manifest — Work Smarter, Not Harder

One enumerated list of **everything we hand in**, so each teammate can verify the *complete* package
against a single source of truth and fix what they think is missing. Two independent tracks.

## Status at a glance

**✅ Implemented & verified**
- **Graded build:** 3-container Docker app · **Job Queue (+5)** · **Online Forum (+10)** · **Azure deploy + CI/CD (+10)** · live HTTPS URL
- **Report** (`REPORT.md`, 1335 tests) · **README** (run + test instructions) · risk assessment
- **Per-member commits** present — all three members commit under their own identity, so the per-member
  grading requirement is met. Counts drift with every push; read them from the repo rather than from here:
  `git shortlog -sn --all`. A `.mailmap` unifies the two identities Elad committed under (GitHub noreply +
  the campus address), so that command lists **three** contributors, not four.
- **Show Off gallery (Track B): ✅ SUBMITTED 29 Jul** (`207490913.zip` — team-approved, uploaded to Moodle)

**⬜ Still open**
- **F5 workout generator — dashboard display** — AI side built + wired into `/predict` (Shiri); the dashboard doesn't relay or render `plan` yet — the one open *graded* gap (web tier · [#410](https://github.com/LiorBenSidi/work-smarter-not-harder/issues/410))
- **Demo video** of the app — not recorded yet (team; script at `presentation/WSNH Demo Video Script.md`)
- **Paste the repo link** into the Moodle final-project box (when it opens) — Lior _(Show Off zip ✅ uploaded 29 Jul)_
- **Seed prod · VM up · joint sign-off** before the TA review

Naming: demo **video** = `VID_<id1>_<id2>_<id3>.mp4`; the Show Off **zip** = one member's ID (`207490913.zip`).
The graded project has **no zip** — it's a repo link.

---

## Track A — Final project (graded · 50%) · due **23 Aug**

Rubric (`docs/GUIDELINES.md`, the TA's `WSNH_Guidelines`, 8 Jul): **75** proposal app + **5** Job Queue
+ **10** Online Forum + **10** Azure deploy & CI/CD. Penalties: −5/bug, −5/week late.

| Deliverable | Where | Owner | Status |
|---|---|---|---|
| The application | this repo @ `main` | all | ✅ `docker compose up --build` (3 containers, only `web` published) |
| Live URL over HTTPS | app.worksmarternotharder.dev | Elad (deploy) | ✅ live, auto-deploy + rollback |
| **Report** | [`docs/REPORT.md`](REPORT.md) | all (Lior drafted) | ✅ current — **1335 tests** (1317 pass / 18 env-gated in CI). The single source is the live `.md`; the stale 2026-07-11 `REPORT.pdf` was removed — regenerate a fresh PDF from this only if the TA wants a file. |
| Rubric / guidelines | [`docs/GUIDELINES.md`](GUIDELINES.md) | — | ✅ |
| Roadmap | [`docs/ROADMAP.md`](ROADMAP.md) | — | ✅ |
| Presentation + demo video | `presentation/` (see the checklist) | all | 🟡 deck ✅ (presented 16 Jul); **demo video ⬜ to record** → `VID_<ids>.mp4` |
| Submission checklist | [`presentation/WSNH Submission Checklist.md`](../presentation/WSNH%20Submission%20Checklist.md) | — | ✅ |

**Hand-in format** (per [`docs/Proj_Guidelines.pdf`](Proj_Guidelines.pdf) p11–12 — text+visual dual-read verified): submit **(1) the GitHub repo link — "no more zips"**, **(2) a video** of the app in use, and **(3) the report** (`docs/REPORT.md` — app · features · *tests per feature* · risk assessment). `README.md` must exist with run + test instructions; **−5 each time the code doesn't run**. So the report lives in the repo (no PDF required) and there is **no submission zip** for the graded project — only the Show Off gallery (Track B) uses a zip.

### Verify-your-own-lane before sign-off
- **Lior** — web tier · whole data layer (`db.py` CRUD, indexes, `$jsonSchema`, seed, backup) · observability ·
  the 3-container build · the CI gate · the CI/CD pipeline · web/data integration/system/security tests. ✅ shipped.
- **Elad** — live Azure deploy · media/attachments (+ size caps) · rate-limiting · stress · cross-container
  test-runner · the AI job queue (+5). ✅ shipped (his own lane-validation, #388).
- **Shiri** — the AI model (`ai/`): real `/predict` ✅ landed; **F5 workout generator's AI side ✅ built and
  wired into `/predict`** (catalog, split resolution, exercise selection). F6's `program` input (#276 P7)
  still unresolved — the generated plan isn't fed into `_program_recommendations` yet.

### Open before hand-in (human steps / not built)
- [ ] **Submit the GitHub repo link** in the Moodle final-project box when it opens (format is settled above:
      repo link + video + report, **no zip**). Only residual: confirm *which* Moodle box — not a build task.
- [ ] **F5 workout generator — dashboard display** (web tier) — AI side done; #410.
- [ ] **Seed prod once** before the TA review (`db/README.md` command) and confirm the **Azure VM is up**
      (instructor auto-shutdown ~23:50 UTC).
- [ ] **Record the demo video** end-to-end on the real model.
- [ ] **Joint sign-off** — all three review `main` and agree it *is* the submission.

---

## Track B — "Show Off Your Project" gallery (optional · **NOT graded**) · due **1 Aug** — ✅ **SUBMITTED 29 Jul**

Moodle `id=266452` (Noam, 16 Jul). Per `instruction_for_students.pdf`: one zip named after **one** member's
ID, built and uploaded by Lior. Package built & verified against the instruction:

| Item (in [`presentation/showoff/`](../presentation/showoff/)) | Requirement | Built | ✓ |
|---|---|---|---|
| [`metadata.json`](../presentation/showoff/metadata.json) | title · ~20-word + ~100-word desc · team · links | ✅ in-repo | ✅ |
| [`poster.pdf`](../presentation/showoff/poster.pdf) | A3 | 297 × 420 mm — **renders inline on GitHub** | ✅ |
| [`thumb.png`](../presentation/showoff/thumb.png) | thumbnail | renders inline | ✅ |
| [`demo.mp4`](../presentation/showoff/demo.mp4) | 20–90 s · 1920×1080 · MP4 · silent | 27.9 s — **plays inline on GitHub** | ✅ |
| [`207490913.zip`](../presentation/showoff/207490913.zip) | the exact Moodle upload (named after **one** member's ID) | ✅ in-repo | ✅ |

**The whole Show Off package is committed to [`presentation/showoff/`](../presentation/showoff/)** — the exact
`207490913.zip` (the Moodle upload), **plus its unpacked files so Elad & Shiri could review the poster, thumbnail, and demo
video inline on GitHub** (not just the metadata text). The zip is named after **one** member's ID per the
instruction (all three names are inside `metadata.json`). **✅ Reviewed + approved by Elad & Shiri and UPLOADED to Moodle `id=266452` on 29 Jul 2026 — Track B complete.**

---

*This manifest tracks deliverables, not code. Flip items to ✅ as they land; keep it consistent with the
checklist and `docs/REPORT.md`.*
