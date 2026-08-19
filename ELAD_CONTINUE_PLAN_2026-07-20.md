# PLAN — Elad, continue the lane (2026-07-20)

> Local working plan (NOT committed). Owner: Elad. Follows `SESSION_PLAN_2026-07-19.md`.

## Where the lane stands
All features merged + deployed. Open issues (#374 #360 #358 #331 #276) are **teammate-owned**; nothing
assigned to me. What remains is **submission hardening**, in three buckets.

## Bucket 1 — Elad-lane test validation (the missing third of the team-wide pass)
Issue #360 = Lior's web/data/CI/frontend tests. #358 = Shiri's AI tests. **Nobody validated my lane.**
The TA reads test code and docks for redundancy. Audit done (22 files). Result:

- ✅ **Zero** dead scaffolds / `assert True` / `NotImplementedError` — unlike `test_ai.py` (#358).
- ❌ ~15 **semantic duplicates**, worst in media:
  - 413 oversize × 3: `Security_Tests/test_media_limits.py:16` · `Negative_Tests/test_messages_media_negative.py:101` · `Integration_Tests/test_elad_lane_journey.py:73`
  - 400 bad MIME × 3: `test_media_limits.py:24` · `test_messages_media_negative.py:94` (parametrized superset) · `test_elad_lane_journey.py:74`
  - third-party DM attach 403: `test_media_limits.py:40` ↔ `test_messages_media_negative.py:146`
  - foreign-blob bind: `test_media.py:118` ↔ `test_messages_media_negative.py:123`
  - foreign post 403 / bogus post 404: `test_media.py:149` ↔ `test_messages_media_negative.py:132`
  - `DEFAULT_TARGET` asserted × 3: `test_jobqueue.py:555` · `test_ai_queue_contract.py:72` · `test_scale_contract.py:44`
  - queue: `test_ai_queue_api.py:283` ⊂ `:60`; `:82` ⊂ `:257`; `:189` ⊂ `Security_Tests/test_ai_queue.py:52`;
    `:126` ⊂ `Security/test_ai_queue.py:137`; `test_jobqueue.py:79` ⊂ `Security/test_ai_queue.py:42`;
    `test_jobqueue.py:475` ⊂ `:416`
  - engagement layered × 3: `test_engagement.py:51` ↔ `test_db_engagement.py:77` ↔ `test_elad_lane_journey.py:84`
- ❌ 5 **vacuous** asserts:
  - `test_scale_contract.py:45` — unreachable after `:44`'s equality
  - `test_ai_queue_live.py:51` — name/docstring promise "real worker processes", body only asserts `workers >= 1`
  - `test_rate_limit.py:118` — asserts `!= 429` with the limiter **off** (no code path can 429)
  - `test_scale_contract.py:87` / `:79` — assert on `__doc__` / compose **comments**, not behaviour
  - `test_media.py:109` — under-cap control already covered by 4+ tests in the file
- ⚠️ `test_pool_scaling.py:31` skips on `CORES < 4` — **nothing asserts the CI runner has 4 cores**, so
  the +5 parallelism claim may never execute in CI. Verify, then either pin it in
  `test_deploy_contract.py` (as the `E2E_BASE_URL` wiring is pinned at `:141`) or make the gate loud.
- ℹ️ `test_scaffold.py` is a **real** test file (`:26` shells `git ls-files .env` — genuinely fails on a
  committed secret). Only its line-1 docstring ("Replace/extend with real feature tests") reads scaffold-y.

**Rule for the pass:** keep the *stronger* test of each pair (usually the `Negative_Tests` version — it
also asserts no bytes stored), delete the weaker, never drop feature coverage. Same standard the team
applied in #384/#385/#386.

## Bucket 2 — Elad-lane doc defects (all mine, all stale-fact)
| File:line | Defect |
|---|---|
| `docs/CICD_REPORT.md:75-78` | **Evidence section still italic placeholders** — no green-run link, no blocked-deploy link, on a graded +10 doc. Deploy live since 16 Jul; the runs exist in Actions. |
| `docs/REPORT.md:209,214,226` | §4 counts Unit **375** · Integration **441** · Security **97** contradict §3 (`:170`) and the suite (376 · 386 · 86, 1066 collected). Wrong numbers one screen below the right ones, inside the graded report. |
| `PERSON3.md:51-52` | Calls the model a **placeholder**; scaling row cites only the proxy 2.86× / 1.60×, never the real-model ~2.5× / ~1.54× (#380/#381). Same staleness class #383 fixed in `CLAUDE.md`. |
| `docs/JOB_QUEUE_PLAN.md:32,112` | "placeholder body verbatim" — present tense, model has landed. |
| `README.md:228` | "747 passing / 36 env-gated (783 collected)" — **283 tests stale**. |

Verified live: `pytest --collect-only` = **1066** (Unit 376 · Integration 386 · Negative 164 · System 15 ·
Full-System 27 · Security 86 · Stress 12). `REPORT.md` §3 + header are correct; §4 is not.

## Bucket 3 — STRESS_REPORT rec #2 (the only unticked §4 row on my tier)
`docs/STRESS_REPORT.md:55`: rate-limit storage is per-process `memory://`; safe *only* because
`WEB_WORKERS` defaults to 1. Latent conditional gap. Decision fork — see below.

## Not mine / blocked
- `presentation/WSNH Submission Checklist.md` stale ticks (783/747 at `:27`,`:42`) + unticked deliverable
  boxes — team file, flag on #374, don't unilaterally edit.
- `README.md:72,230` + `presentation/README.md:38` still call `ai/` a placeholder — Lior/Shiri files, flag.
- Live-VM "does see" scaling re-run — needs SSH, human.
- Azure VM up at submission time (instructor auto-shutdown) — can only be done 23 Aug.

## Execution order
1. Bucket 2 (fast, high grade-visibility) → PR → CI green → self-merge.
2. Bucket 1 (test pass) → PR, mirroring #384/#385/#386's format → self-merge.
3. Bucket 3 per the answered fork.
4. Comment on #374 with what landed + the flags above.

---

## ✅ DONE — all three buckets shipped (2026-07-20)

**PR #387 merged → `c7ddfce`.** Bucket 2. CICD_REPORT evidence section filled with real runs; REPORT §4
counts corrected (376/386/86 + Negative 164 + Full-System 27); README de-staled by 283 tests;
PERSON3 scaling row leads with the real-model numbers; JOB_QUEUE_PLAN present tense fixed.

**PR #388 merged → `606ec8f`.** Buckets 1 + 3. 16 duplicate/vacuous checks removed, 2 prose guards made
executable, rec #2 closed by guard, 2 flaky hung-worker tests de-flaked. Suite **1053** (CI 1011/42).

**Main green, auto-deployed, prod `/ready` = 200** (run 29742232595, all six jobs).

### Two findings worth remembering
1. **`build` needs `[checks, compose-e2e]` — NOT `e2e-browser`.** A red browser-e2e has shipped to prod
   three times. Deliberate (flaky headless stage, coverage duplicated in compose-e2e) but was undocumented;
   now an accepted risk in REPORT §5.5. Flagged to Lior on #374 — his pipeline, his call whether to gate it.
2. **A PR proves R1.3, not R2.2.** On a PR, `build` is skipped by its own event guard regardless of test
   results, so PR runs are useless as evidence that the test gate blocks deploys. Only push-to-`main`
   failures demonstrate the `needs:` chain. My first draft of the evidence section got this wrong.

### Toolchain notes
- Full suite ~1m45s normally; one run took 9m21s under load and produced a **timing-flaky** failure in
  `test_jobqueue.py`'s hard-timeout tests. Fixed by polling instead of sleeping — if a queue timing test
  fails once and passes standalone, suspect the sleep, not the queue.
- `gh run view <id> --json jobs` is the fast way to see which gate blocked which stage.

## ✅ Session part 2 — the three forks, all answered "recommended"
- **e2e-browser gate → left as a documented accepted risk** (REPORT §5.5 + flagged to Lior on #374). Not
  my pipeline to change unilaterally; a TA reading §5.5 sees a team that found its own gap.
- **PR #389 merged** — submission-checklist fact fixes: line 42 was **ticked as verified** while carrying
  747/36 of 783 (→ 1011/42 of 1053); four Deliverables boxes whose own prose said "✅ built" were unticked;
  the Shiri must-fix row still claimed "every prediction is Moderate"; the Lior+Elad timeout tune was
  unticked but already answered in SCALING_REPORT. Facts only, no restructure, TA banner untouched.
- **Live-VM re-run → deliberately dropped**, and SCALING_REPORT now says *why* rather than leaving an
  implied TODO (both variables already controlled for; a run would load the prod VM serving the demo).

## What is left (nothing buildable)
1. **Live-VM "does see" scaling re-run** — needs SSH. Human.
2. **Azure VM up at submission time** — instructor auto-shutdown (23:50 UTC) already ate one deploy
   (29630794935, SSH timeout 04:40 UTC). Can only be confirmed on 23 Aug.
3. **Submission mechanics unconfirmed with the TA** — zip vs Moodle vs repo link; report as PDF or live
   `docs/REPORT.md`. Unowned, gates the hand-in. Raised on #374.
4. **`presentation/WSNH Submission Checklist.md` stale ticks** — line 42 is *checked* with 747/36 of 783
   (real: 1011/42 of 1053), and every Deliverables box is unticked though the prose calls them built.
   Team file — flagged on #374, deliberately not edited unilaterally.
5. Teammate-owned: #360 (Lior), #358 + #276 (Shiri), #331 hot-path rows (Lior),
   `presentation/README.md:38` "every prediction reads Moderate" (stale).
