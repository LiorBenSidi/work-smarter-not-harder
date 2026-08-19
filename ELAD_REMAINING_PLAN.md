# Elad — remaining work (PLAN)

> Updated 2026-07-10 after PR #195 (queue self-heal). Scratch file, not committed.

## Done 2026-07-10

| PR | What |
|---|---|
| #214 | **Cross-feature journeys over my lane** (media × engagement × caps): 4 in-process journey tests + a live real-HTTP twin in compose-e2e (incl. the one leg an in-process client can't prove — a genuine 10 MB+1 body shed 413 at the WSGI layer), plus live queue-health counters (`pool_rebuilds`/`abandoned` must be 0 in CI — a silent worker death would otherwise be invisible since the queue self-heals). compose-e2e ran both live legs green on the PR |
| #210 | **Received-engagement metric built** (GUIDELINES §3.3 — the last unbuilt Forum sub-feature; taken under Lior's rule "unassigned → Elad", now written into ROADMAP/PERSON3): `GET /me/engagement` (votes others cast on your posts/comments; counts only, self-votes excluded, anonymous posts credit the real author) + a "Community engagement" card on the Profile screen. Additive db function + seam + fake, 13 TDD tests. Closed #208. Live-verified (401 gate on prod) |
| #212 | Post-#210 sync: restored the all-seven presentation claims (#211 had softened them minutes before the feature landed), README built-list + suite counts (697/36 — green on Windows too after Lior's #209) |
| — | **Issues #207 + #208 filed** (Windows test portability · presentation overclaim) — both closed same day (Lior fixed #207 in #209; #208 closed by #210) |
| #199 | **Forum flood stress test** (GUIDELINES §3.6): 128-post flood as a real user → 429 engages, no 5xx, no drops, admitted posts cleaned up. Also wired `test_load.py` into the compose-e2e runner — its docstring claimed the runner ran it, but the runner command never included it, so **none of the burst tests ever ran in CI** until now. compose-e2e itself caught a test-order coupling (login flood exhausts `/login`'s budget) — fixed + documented. REPORT matrix: Forum stress cell filled; Load/abuse row de-staled |
| #200 | **Post-#195 accuracy pass**: ROADMAP's stale "Still to build" line (the only text assigning the Forum real-time layer to me — it's Lior's) rewritten; presentation-kit queue sections de-staled ("OOM on the 1 GB VM" → RAM-agnostic reasoning; new worker-dies/hangs Q&A with the #195 answer); the "For Elad" robustness note marked RESOLVED. Flagged, not edited (Lior's content): TA drill Q13 claims the per-user vote total exists — it's still open |
| #195 | **Closes issue #186** (Lior's adversarial-review findings, items 1+2; item 3 was #187): the job queue now **self-heals a broken process pool** (dead worker → pool replaced, generation-guarded, submit retried once, lost job = retryable 503, `pool_rebuilds` in stats) and **reaps hung workers** (`AI_JOB_HARD_TIMEOUT_SECONDS`, default 120s, contract-pinned > the /predict deadline; abandoned slot reclaimed, late completion never double-releases; fully-hung pool replaced). 15 new tests, TDD red-first, both guards mutation-checked. Compose files surface the new knob. REPORT §5.2 gained the two rows; JOB_QUEUE_PLAN documents the deliberate non-fixes (no `max_tasks_per_child`, no `Future.cancel()`). |

## Done today (all merged + deployed)

| PR | What |
|---|---|
| #187 | **Bug:** `ai/Dockerfile` had no gunicorn `--timeout`, so it used the default 30s — *exactly* `AI_PREDICT_TIMEOUT_SECONDS`. A predict running to the deadline raced a worker SIGKILL and the 504 degrade was unreachable. Fixed (`--timeout 60`) + mutation-tested guard |
| #190 | Re-argued every "because the VM has ~1 GB" justification across 11 files. Decisions unchanged; reasons rewritten. Corrected `SCALING_REPORT`, which still claimed prod pins `AI_QUEUE_WORKERS=2` (it's 4) |
| #191 | Round-2 sweep: `PERSON1.md` (the line Shiri reads while measuring), `CLAUDE.md` (risk assessment listed open — it shipped; Forum media listed open — it shipped), `PERSON3.md`, `ARCHITECTURE-REVIEW.md` |

## Live-stack verification (read-only, done 2026-07-09)

All run-sheet claims hold against `https://app.worksmarternotharder.dev`:

- `/health` → `{"service":"web","status":"ok"}` · `/ready` → 200 (so `ai` + `db` are both up)
- HTTP → HTTPS **308** redirect; Let's Encrypt cert valid **8 Jul → 6 Oct 2026** (covers the 23 Aug submission)
- Security headers present: HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, CSP `frame-ancestors`
- Internal surfaces correctly **not** public: `/jobs`, `/queue/stats`, `/predict` → 404
- VM ports: **5000, 27017, 8000 closed**; only **80 + 443** open (Caddy). The only-`web`-exposed contract holds in prod
- `/.well-known/assetlinks.json` → 404, confirming the #179 TWA revert is deployed
- PWA `/manifest.webmanifest` + `/sw.js` → 200

---

## What's left

### Needs you (a human) — cannot be automated
1. **The live deploy demo (+10).** The single biggest item on your grade. Everything is wired and proven:
   `DEPLOY_ENABLED=true`, auto-deploy green four times today, live stack verified above.
   Run-sheet: `docs/DEPLOY_DEMO.md`. *This is just the performance.*
2. **UptimeRobot monitor (R9).** Needs the dashboard. Point it at `/health`.
3. **Send the corrected messages** to Shiri and Lior (the originals had a duplicated block + dead VM numbers).
4. **Settle Forum ownership with Lior.** He told you the Forum is your lane. His own PR #184,
   `PERSON2.md:45-47`, `ROADMAP.md:111` and `git blame` (`messages.py` = 7/7 Lior) all say the real-time
   layer is his and yours is media. `REPORT.md` §6 is currently correct — protect it. Grading is per-member.
5. **Decide on the reverted TWA work** (#176 → reverted by #179). Accept, or reopen with Lior. Not unilaterally.

### Blocked on a teammate
6. **Final `AI_CLIENT_TIMEOUT` tune** — waits on Shiri's predict-time + peak RAM. Joint Lior+Elad call.

### Flag to Lior (not yours to build)
7. **Received-engagement metric** — GUIDELINES §3.3: *"a per-user total in a personal area"*. The last open
   Forum sub-feature besides cold seeding (Shiri's). It lives in `web/` on top of Lior's vote layer → **his**.
8. **Three Windows-only test failures** — `test_backup_script` ×2, `test_logging_config` ×1. Pre-existing on
   clean `main`, in his files, green on Linux CI.

### Optional
9. **Re-measure scaling on the real VM.** Largely moot: #190 established the benchmark's `--cpus=4` cap now
   matches the VM's 4 vCPU, so the measured **2.86×** *is* prod's number. A live re-run would upgrade
   "should see" → "does see".

### Nothing else
Job queue, scaling, cross-container harness, fault-isolation, stress, media, rate limiting, risk assessment,
and the `ai` timeout bug — all merged, deployed, green.
