# PLAN — issue sweep + continue Elad lane (2026-07-19)

> Local working plan (NOT committed). Owner: Elad. Continues `CONTINUATION_PLAN.md`.

## Open-issue ownership map (verified against code + gh)
| # | Author | Assignee | Lane | Closeable by me? |
|---|--------|----------|------|------------------|
| 374 | Lior | — | Submission-coordination **WIP tracker** | No — living tracker, "nothing ready to submit yet" |
| 360 | Lior | Lior | Lior's web/data/CI test semantic pass | No — his active task |
| 358 | Lior | Shiri | Delete redundant `test_ai.py` (skip + `NotImplementedError`, still on disk) | No — Shiri's lane |
| 331 | Lior | — | Unbounded reads. **My 2 rows DONE (#334)**; remaining = Lior's self-limited rows | No — his tracker |
| 276 | Lior | Shiri | AI model backlog | No — Shiri's lane |

## Verified facts
- `web/services/db.py:622 forum_received_engagement` — **scoped + indexed** (`find({"author": username})` on posts & comments). #331 my row is DONE. **#374's "forum_received_engagement row still open" is STALE.**
- `#326` (I authored, "owner: Shiri") — **already closed today** (COMPLETED via #376), real-model re-baseline done; assignee empty.
- Real RF model has **landed** (`ai/model/model.pkl` 5 MB + `train.py` + `training_report.json`) — CLAUDE.md "placeholder" note is stale.
- `tests/Unit_Tests/test_ai.py` = the skipped TDD scaffold #358 targets (Shiri's to delete).

## Actions
### Confident (in-lane, no fork)
1. Comment on **#374** confirming my lane rows (deploy/scale/job-queue/media/rate-limit/real-time) and **correcting** the stale `forum_received_engagement` claim (done in #334).
2. **Continue my work:** review + confirm/correct the Elad-lane rows in `docs/REPORT.md` against the real model + current code (the concrete "continue" ask in #374). Branch → PR → CI green → self-merge.

### Forks (asked before acting) — ANSWERED
- **A — Shiri issue tagging.** User: "leave it" — no action on #326. #358/#276 already assigned `shiriHaboob`.
- **B — Lior's issues.** User: "comment confirmations, don't close." Nothing closed.

## ✅ DONE (2026-07-19)
- **PR #378 merged → main `5769cb7`.** SCALING_REPORT: reframed the stale present-tense "shipped model is a
  placeholder" (real RF has landed) + new "Re-baselined on the real model (#326/#376)" section with the fresh
  real-model numbers. Claims verified vs `scaling_benchmark.py` / `test_scale_contract.py` / `ai/app.py`. CI green.
- **#374 comment posted:** confirmed my §5.3/§5.4/queue rows; corrected the stale "forum_received_engagement
  row still open" (done #334); flagged "forum real-time = Lior per §6"; flagged CLAUDE.md status still says
  "placeholder" (Lior's section — flag, not edit).
- No open issue was closeable by me (all teammate-owned active work / living trackers). Left to owners per team rule.

## ✅ DONE part 2 — advance my lane (2026-07-19)
- **PR #379 merged → main `23262f3`.** Full-system re-stress on the REAL model (STRESS_REPORT §7): re-ran
  `locustfile_full_system.py` at 100u + 200u on main @ `5769cb7` (web 1×16, real RF baked in). Results: 100u
  77.5 RPS / p95 190 ms / 0 feature fails; 200u 134 RPS / p95 1.0 s / 0 feature fails, no 5xx/429/503. `/checkin`
  held (200u p95 570 ms); ai CPU 26–97 % (real work, was idle on placeholder) but web saturates first → no shed
  under full-system load. Closed rec #5, updated §2 AI-path row, signposted §1 header.
- Toolchain notes for next time: locust broke in anaconda base (zope namespace conflict) → use venv at
  `C:\Users\eladn\lenv` (`Scripts/locust.exe`). Deep scratchpad path hits Windows 260-char limit → short venv path.
  Docker Desktop must be started first. Fresh unique DM hub via `LOCUST_HUB` avoids stale `stress_hub` state.
- **#374 follow-up posted:** perf docs now confirmed on the real model (#378 SCALING + #379 STRESS), no longer
  describe a shipped placeholder.

## ✅ DONE part 3 — real-model scaling, both axes (2026-07-19)
- **PR #380 merged:** Axis-1 pool 1→4 measured **directly on the real model** = **~2.5×** (59→150 RPS, p50 133→52 ms,
  0 fail; 2 runs). Two standalone `ai` containers, `--cpus=4`, real target. Confirms the proxy's 2.86×.
- **PR #381 merged:** Axis-2 replicas 1→2 on the real model = **~1.54×** (66→~101 RPS, in-network benchmark).
  Confirms the proxy's 1.60×. Both axes now real-model-measured (pool ~2.5× · replicas ~1.5×, multiplying).
- **PR #382 merged:** REPORT §5.3 scale row now cites the real-model numbers, not just the proxy — keeps the
  graded top-level report consistent with SCALING_REPORT.
- Toolchain note: in-network `docker run` benchmark needs `MSYS_NO_PATHCONV=1` (Git Bash mangles `/bench`);
  scale compose defaults `AI_WORKER_TARGET` to the real model, so no override needed.

## Session end state
- **5 PRs merged** (#378 #379 #380 #381 #382). Both perf docs (SCALING + STRESS) + REPORT §5.3 fully
  real-model-measured. All open issues left to their owners per team rule (#374 confirmations posted).
- **Blocked / needs Elad-the-human:** live-VM "does see" re-run (SSH). Everything else in-lane is done/merged.
