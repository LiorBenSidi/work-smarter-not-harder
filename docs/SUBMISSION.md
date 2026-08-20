# Submission manifest — Work Smarter, Not Harder

One enumerated list of **everything we hand in**, so each teammate can verify the *complete* package
against a single source of truth and fix what they think is missing. Two independent tracks.

## Status at a glance

**✅ Implemented & verified**
- **Graded build:** 3-container Docker app · **Job Queue (+5)** · **Online Forum (+10)** · **Azure deploy + CI/CD (+10)** · live HTTPS URL
- **Report** (`REPORT.md`, 1329 tests) · **README** (run + test instructions) · risk assessment
- **Per-member commits** present — all three members commit under their own identity, so the per-member
  grading requirement is met. Counts drift with every push; read them from the repo rather than from here:
  `git shortlog -sn --all`. A `.mailmap` unifies the two identities Elad committed under (GitHub noreply +
  the campus address), so that command lists **three** contributors, not four.

**⬜ Still open**
- **F5 workout generator — dashboard display** — AI side built + wired into `/predict` (Shiri); the dashboard doesn't relay or render `plan` yet — the one open *graded* gap (web tier · [#410](https://github.com/LiorBenSidi/work-smarter-not-harder/issues/410))
- **Demo video** of the app — not recorded yet (team; script at `presentation/WSNH Demo Video Script.md`)
- **Paste the repo link** into the Moodle final-project box — Lior
- **Upload the poster zip** to its own Moodle box (Track B, due **25 Aug**) — the 29 Jul upload was built to
  rules that were reversed on 18 Aug and has been **deleted**; the box is empty until the rebuilt zip goes up
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
| **Report** | [`docs/REPORT.md`](REPORT.md) | all (Lior drafted) | ✅ current — **1329 tests** (1311 pass / 18 env-gated in CI). The single source is the live `.md`; the stale 2026-07-11 `REPORT.pdf` was removed — regenerate a fresh PDF from this only if the TA wants a file. |
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

## Track B — "Show Off Your Project" poster package (**not graded, but required**) · due **25 Aug** — ⬜ **NOT SUBMITTED**

Its own Moodle box ([`id=266452`](https://moodle25.technion.ac.il/mod/assign/view.php?id=266452)), separate
from Track A. **Two dates, and they differ:** the announcement asks for *"August 25th (i.e. a couple days
after submitting the project)"* (Noam, 16 Jul), while the box's own close time is **Sun 30 Aug 2026, 11:59 PM**
— the same instant as Track A. We target **25 Aug**: it honours the request, and the box staying open to the
30th is margin, not licence.

The box description still reads *"The zip should contain exactly what described in
`instruction_for_students.pdf`"*, but **that file is no longer attached to the section** — its resources are
`how to submit.pdf`, `check_submission.sh`, and the "Update (easier!) submission" note. The description is
un-updated text; **`how to submit.pdf` governs.**

Governed by **`how to submit.pdf` ("Updated on 2026-08-18")**, which supersedes the 16 Jul
`instruction_for_students.pdf` and **reverses several of its rules**:

| Rule | 16 Jul | 18 Aug (governing) |
|---|---|---|
| `thumb.png` | **required** — *"thumbnail of the above image"* | **forbidden** — the zip must hold *"exactly these files and nothing else"* |
| `poster` field in `metadata.json` | **required** — *"poster.type is `pdf` or `image`"* | **forbidden** — *"Do not add a `poster` field"*; the gallery finds the poster by filename |
| `repo_url` | absent (the repo went in `links`) | **[required] for every submission** |
| poster format | *"An image (PNG/PDF) of size A3"* | **PDF only, A3, one page** |
| `installation.md` / `install.sh` | required to run the real code | dropped — the repo must run via `docker compose up` |
| video via an external link | allowed (`links` → *"Demo Video"*) | **won't play** — must be attached as `demo.mp4` |

The 29 Jul upload was built to the old rules, so it was **deleted from Moodle** rather than left standing as
a non-compliant submission.

| Item (in [`presentation/showoff/`](../presentation/showoff/)) | Requirement (18 Aug) | Measured | ✓ |
|---|---|---|---|
| [`metadata.json`](../presentation/showoff/metadata.json) | title · ~20-word + ~100-word desc · **all** members · `repo_url` | 20 / 104 words · 3 members · `repo_url` present · no `poster`, no `launch` | ✅ |
| [`poster.pdf`](../presentation/showoff/poster.pdf) | A3 · PDF · one page | **297.0 × 420.2 mm, 1 page, portrait** — renders inline on GitHub | ✅ |
| [`demo.mp4`](../presentation/showoff/demo.mp4) | optional · 20–90 s · 1920×1080 · MP4 · silent | **27.9 s · 1920×1080 · h264 · no audio stream at all** — plays inline on GitHub | ✅ |
| [`207490913.zip`](../presentation/showoff/207490913.zip) | **exactly** those files, flat, named after one member's ID | **3 entries, no folders, no `thumb.png`** | ✅ |

**No `launch` block — deliberately.** Declaring one activates the compose Annex, and the root
`docker-compose.yml` fails it twice: it has `volumes:` both service-level and top-level (rule 1 rejects
*any* entry), and no service declares `mem_limit`/`cpus` (rule 4). The Annex applies only to a live launch
(*"If you're only submitting a poster and/or video, none of this applies to you"*), so the field is omitted
and the live site stays reachable through `links`.

**Repo access.** The poster rules also require staff to clone *"without interactive authentication"*. The
repo is public today; if it goes private before submission, **`cnoam` and `EladKal6` must be added as
collaborators** — the same requirement Track A carries.

**Verify before uploading:**

```sh
bash check_submission.sh presentation/showoff/207490913.zip   # official checker from Moodle; needs Docker
```

> ⚠️ **The instructions change without announcement.** On 18 Aug alone the box was renamed twice, its close
> date moved, and the instructions PDF was replaced; the 16 Jul announcement was itself edited in place
> (*"August 1st"* → *"August 25th"*). **Re-check Moodle immediately before uploading** —
> [#531](https://github.com/LiorBenSidi/work-smarter-not-harder/issues/531) carries the baseline hashes of
> every instruction file we hold.

---

*This manifest tracks deliverables, not code. Flip items to ✅ as they land; keep it consistent with the
checklist and `docs/REPORT.md`.*
