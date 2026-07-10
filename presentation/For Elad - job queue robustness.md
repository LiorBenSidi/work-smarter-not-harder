# For Elad — 3 robustness items in the AI job queue (`ai/jobqueue.py` / `ai/Dockerfile`)

> ✅ **RESOLVED (Elad, 2026-07-10).** All three closed: **#3** → PR #187 (`--timeout 60` in `ai/Dockerfile`,
> guard-tested); **#1 + #2** → PR #195 (broken-pool **self-heal** + hung-worker **hard-timeout reaper**,
> 15 new tests, both mutation-checked; issue #186 closed). The stale "1 GB VM" framing → PRs #190/#191
> (docs) + the presentation-kit queue sections (same PR as this note). Kept for the review trail.

Hi Elad — we ran an adversarial review over the whole repo before submission. Your queue is solid (bounded,
process-pool, TTL reaping, the settled-event race is correctly handled — all verified clean). Three robustness
gaps came up in **your** files, so they're yours to judge. None is exploitable today; they matter under real
load / the real model. I verified each against the code (and reproduced #1's mechanism), so they're not false
positives.

> Note: Noam moved us to a **4 vCPU / 32 GiB** VM (was 1 GB). That **downgrades #1 from critical to medium** —
> the OOM trigger it depended on is no longer expected — but the bug is still real, and #1's fix also lets you
> safely run more pool workers / gunicorn workers now that there's headroom.

## 1. (Medium) A dead pool worker permanently wedges *all* predictions — silently
`ai/jobqueue.py` (`submit`, ~line 171) + `ai/app.py` (`/predict`, ~line 72).
If any `ProcessPoolExecutor` worker process dies (OOM/segfault/crash), the executor enters a **permanently
broken** state — every later `executor.submit()` raises `BrokenProcessPool`. `submit()` decrements the slot and
**re-raises**, but `/predict` only catches `QueueFull`, so it becomes a **500 on every request, forever**.
There is no code path that rebuilds the executor (I grepped: zero `BrokenProcessPool` handling).
It's **silent**: web turns the 500 into a graceful "AI unavailable", and `/health` never touches the queue, so
Docker's healthcheck stays green and never restarts `ai`.
**Repro:** submit a job whose worker calls `os._exit(1)` → its future resolves to `BrokenProcessPool` → the very
next `/predict` 500s and never recovers. (I reproduced the `ProcessPoolExecutor` half in isolation — once a
worker dies, a later `submit` raises `BrokenProcessPool` and the pool never self-heals.)
**Fix (either):** catch `BrokenProcessPool` in `submit`/`_on_done` and rebuild `self._executor` under the lock;
**or** make `/health` probe the queue so Docker restarts the container on a wedged pool.

## 2. (Low) A *hung* worker leaks its depth slot forever
`ai/jobqueue.py` (`result`, ~line 207-227; `_on_done`, ~183).
There's no `maxtasksperchild`, no cancellation, no wall-clock reaper. If a worker **hangs** (vs. dies), its
future never completes → `_on_done` never fires → `_pending` is never decremented. `queue.result` times out at
30 s and returns 504, but the slot stays occupied (your own comment notes "the job keeps running — a timeout is
the caller giving up, not a cancellation"). Hang `max_pending` workers → permanent 503.
**Fix:** add `maxtasksperchild` to the pool + a reaper that cancels/replaces a future exceeding a hard wall-clock,
releasing the slot.

## 3. (Low) `ai/Dockerfile` gunicorn has no `--timeout` (dev/CI only)
`ai/Dockerfile` CMD omits `--timeout` → gunicorn default **30 s**, exactly equal to `AI_PREDICT_TIMEOUT_SECONDS`.
On the branch where gunicorn's timer wins it SIGKILLs the worker mid-request instead of a clean 504. Prod is fine
(`docker-compose.prod.yml` overrides to `--timeout 60`), so this is a dev/CI fragility only.
**Fix:** add `--timeout 60` to the `ai/Dockerfile` CMD to match prod.

---
Everything else in the queue verified clean: the depth/settled ordering, TTL reaping vs in-flight, the
submit-failure slot-undo, the vote-pipeline atomicity. Nice work. Ping me if you want to pair on #1.

## Also (minor, your sections) — the "~1 GB VM" framing is now stale
Since Noam resized us to 32 GiB, a few of *your* doc lines still say "1 GB VM / OOM" as the rationale:
`docs/REPORT.md §5` (the queue-saturation, two-workers, and "external store on a 1 GB VM" rows) and the README
job-queue blurb ("unbounded backlog on the ~1 GB VM is an OOM"). The **reasoning still holds** — bounded queue
and one ai worker are both correct regardless of RAM — only the *OOM-on-1GB* premise changed. Worth a light
touch when you're in there (I left them alone since they're your sections). I already retuned the compose:
`AI_QUEUE_WORKERS` 2→4 (realizes your measured 2.86×) and web threads 4→8 — `ai` still 1 gunicorn worker.
