# Submission manifest — Work Smarter, Not Harder

One enumerated list of **everything we hand in**, so each teammate can verify the *complete* package
against a single source of truth and fix what they think is missing. Two independent tracks.

Naming convention for any zip/video: `<id1>_<id2>_<id3>`.

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

### Verify-your-own-lane before sign-off
- **Lior** — web tier · whole data layer (`db.py` CRUD, indexes, `$jsonSchema`, seed, backup) · observability ·
  the 3-container build · the CI gate · the CI/CD pipeline · web/data integration/system/security tests. ✅ shipped.
- **Elad** — live Azure deploy · media/attachments (+ size caps) · rate-limiting · stress · cross-container
  test-runner · the AI job queue (+5). ✅ shipped (his own lane-validation, #388).
- **Shiri** — the AI model (`ai/`): real `/predict` ✅ landed; **F5 workout generator ⬜ not built** (+ F6's
  `program` input, #276 P7). ← the one open **graded** feature.

### Open before hand-in (human steps / not built)
- [ ] **Confirm submission mechanics with the TA** — zip vs Moodle vs repo link; report as PDF or the live
      `docs/REPORT.md`. Nobody's lane yet; **gates the hand-in.**
- [ ] **F5 workout generator** (Shiri) — #276.
- [ ] **Seed prod once** before the TA review (`db/README.md` command) and confirm the **Azure VM is up**
      (instructor auto-shutdown ~23:50 UTC).
- [ ] **Record the demo video** end-to-end on the real model.
- [ ] **Joint sign-off** — all three review `main` and agree it *is* the submission.

---

## Track B — "Show Off Your Project" gallery (optional · **NOT graded**) · due **1 Aug**

Moodle `id=266452` (Noam, 16 Jul). Per `instruction_for_students.pdf`: one zip named after **one** member's
ID, built and uploaded by Lior. Package built & verified against the instruction:

| Item | Requirement | Built package | ✓ |
|---|---|---|---|
| [`metadata.json`](../presentation/showoff/metadata.json) | title · ~20-word + ~100-word desc · team · links | **mirrored in-repo for review** (20-word short desc) | ✅ |
| `poster.pdf` | A3 | 297 × 420 mm | ✅ |
| `thumb.png` | thumbnail | present | ✅ |
| `demo.mp4` | 20–90 s · 1920×1080 · MP4 · silent | 27.9 s · 1920×1080 · silent | ✅ |

The zip is built in the course "Show Off Your Project" folder (outside this repo — it is a Moodle upload,
not repo content). Its text component is **mirrored at [`presentation/showoff/metadata.json`](../presentation/showoff/metadata.json)**
so the team can review the gallery title / descriptions / links; the binaries (poster · thumb · demo) stay
in the course folder. **One thing to confirm before upload:** the instruction asks the zip be named after
**one** member's ID (e.g. `<id>.zip`); the current build uses all three IDs — decide the final filename.

---

*This manifest tracks deliverables, not code. Flip items to ✅ as they land; keep it consistent with the
checklist and `docs/REPORT.md`.*
