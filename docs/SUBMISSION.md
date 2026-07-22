# Submission manifest — Work Smarter, Not Harder

One enumerated list of **everything we hand in**, so each teammate can verify the *complete* package
against a single source of truth and fix what they think is missing. Two independent tracks.

## Status at a glance

**✅ Implemented & verified**
- **Graded build:** 3-container Docker app · **Job Queue (+5)** · **Online Forum (+10)** · **Azure deploy + CI/CD (+10)** · live HTTPS URL
- **Report** (`REPORT.md`, 1063 tests) · **README** (run + test instructions) · risk assessment
- **Per-member commits** present (Lior 308 · Elad 43 · Shiri 11 — the per-member grading requirement is met)
- **Show Off package** built & verified (metadata · A3 poster · thumb · demo · zip)

**⬜ Still open**
- **F5 workout generator** — the one open *graded* feature (Shiri · [#276](https://github.com/LiorBenSidi/work-smarter-not-harder/issues/276))
- **Demo video** of the app — not recorded yet (team; script at `presentation/WSNH Demo Video Script.md`)
- **Paste the repo link** into the Moodle final-project box (when it opens) + **upload the Show Off zip** (Lior)
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
| **Report** | [`docs/REPORT.md`](REPORT.md) | all (Lior drafted) | ✅ current — **1063 tests** (1018 pass / 45 env-gated in CI). The single source is the live `.md`; the stale 2026-07-11 `REPORT.pdf` was removed — regenerate a fresh PDF from this only if the TA wants a file. |
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
- **Shiri** — the AI model (`ai/`): real `/predict` ✅ landed; **F5 workout generator ⬜ not built** (+ F6's
  `program` input, #276 P7). ← the one open **graded** feature.

### Open before hand-in (human steps / not built)
- [ ] **Submit the GitHub repo link** in the Moodle final-project box when it opens (format is settled above:
      repo link + video + report, **no zip**). Only residual: confirm *which* Moodle box — not a build task.
- [ ] **F5 workout generator** (Shiri) — #276.
- [ ] **Seed prod once** before the TA review (`db/README.md` command) and confirm the **Azure VM is up**
      (instructor auto-shutdown ~23:50 UTC).
- [ ] **Record the demo video** end-to-end on the real model.
- [ ] **Joint sign-off** — all three review `main` and agree it *is* the submission.

---

## Track B — "Show Off Your Project" gallery (optional · **NOT graded**) · due **1 Aug**

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
`207490913.zip` to upload, **plus its unpacked files so Elad & Shiri can review the poster, thumbnail, and demo
video inline on GitHub** (not just the metadata text). The zip is named after **one** member's ID per the
instruction (all three names are inside `metadata.json`). **Action:** review the files, then **upload `207490913.zip`** to Moodle `id=266452`.

---

*This manifest tracks deliverables, not code. Flip items to ✅ as they land; keep it consistent with the
checklist and `docs/REPORT.md`.*
