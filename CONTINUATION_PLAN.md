# PLAN — continue after Lior's issue updates (2026-07-17)

> Local working plan (NOT committed). Owner: Elad. Follows `ISSUES_AND_STRESS_PLAN.md`.

## What changed on Lior's side (the issues we opened from the stress run)
- **#324** (web capacity / gunicorn workers) → **FIXED in #330**: `WEB_WORKERS`/`WEB_THREADS`
  env-tunable, default **1 worker × 16 threads**, dev↔prod mirrored, SSE-starvation guard.
  Finding: *threads, not workers*, are the lever on the 4-vCPU VM (scrypt releases the GIL).
  **Lior is waiting on my confirmation** to update `STRESS_REPORT.md` rec #1.
- **#325** (`/forum/posts` slowest under load) → **FIXED in #332**: cursor pagination + `created_at` index.
- **#331** (bound all unbounded reads) → **OPEN**. Forum row done (#332 = reference pattern). Two rows are
  **my lane**: `forum_received_engagement` (full `forum_posts` scan on a profile view) +
  `media_store.list_for_target` (all media for a post/DM). Lowest priority, not demo-breaking.
- **#326** (re-run ai stress on real model) → OPEN, owner Shiri. Not my lane.

## Phase A — validate Lior's fixes + close the loop he's waiting on  (PRIMARY)
1. Rebuild the stack (`docker compose up --build -d`) so it carries #330 (1×16) + #332 (pagination). *(running)*
2. Re-stress the **knee region** (100 + 200 users) with `locustfile_full_system.py` — the two stages where
   #324/#325 should show. Capture `/forum/posts` p95 (pagination) + overall p95/RPS knee (threads).
3. Update `docs/STRESS_REPORT.md`:
   - stack line 2×4 → **1×16**; recs #1 (workers→threads, **DONE #330**) + #3 (pagination, **DONE #332**).
   - add a post-fix column / note: did `/forum/posts` p95 drop, did the knee move.
4. Comment on **#324** confirming the workers→threads read (unblocks Lior's report edit).

## Phase B — my #331 lane items (TDD, in-lane, additive)  (SECONDARY)
Branch `fix/bound-unbounded-reads-elad` off fresh `main`.
1. **`forum_received_engagement`** (`web/services/db.py`): bound the scan to the user's involved posts —
   `find({"$or": [{"author": u}, {"comments.author": u}]})` (output identical; loop already ignores others'
   items). Add `author` + `comments.author` indexes in `ensure_indexes` (same slot as #325's `created_at`).
   Fake unchanged (output contract identical). Test: engagement correct AND a foreign user's posts aren't
   scanned (assert via a query-spy / that a huge unrelated post set doesn't change the count).
2. **`media_store.list_for_target`** (`web/services/media_store.py`, my module): add a
   `(target_type, target_id)` index + `.sort("created_at").limit(N)` read bound; enforce a per-target
   attach cap at `bind` time so the data itself is bounded. `MEDIA_MAX_ATTACHMENTS_PER_TARGET` in config.
   Mirror the cap in `FakeMedia`. Tests: over-cap bind rejected; list stays ≤ cap.
3. Local gate (ruff+bandit+pytest) → PR → CI green → self-merge → comment #331 with my rows done.

## ✅ DONE (2026-07-17, PR #334 merged → main f141fa1)
- Re-stressed the fixed stack: @200u **74→122 RPS**, p95 5.7s→1.6s, `/forum/posts` p95 7s→0.8s, 0 5xx. STRESS_REPORT §6 added; recs #1/#3 marked done. Confirmed #324 (threads-not-workers) to Lior.
- #331 my rows bounded. **Reconciled with Lior's #333** (landed mid-branch — moved comments to `forum_comments`): merged main in (no force-push), scoped the still-unbounded posts read + added `forum_posts.author` + the missing `forum_comments.author` index; media cap + compound index unchanged. Told Lior on #331.
- CI green (checks · compose-e2e · browser e2e); full suite 1056 passed. Hot-path #331 rows (history/DM/inbox/notifications) left to Lior's tier.

## Order (as executed)
Phase A first (Lior blocked on it) — but Phase B tests need no live stack, so implement B while the stack
rebuilds/stresses, then run A's locust, then land both.

## ✅ Phase C (2026-07-17 evening) — #338 closed out
- Lior's final #338 comment: the app ⤢ enlarge on videos is **dead to real taps** (native `<video>` swallows
  the pointer; synthetic `.click()` works — why automation couldn't repro). Native fullscreen ⛶ verified
  working on valid files → item 4 was a bad-file artifact, and an app-level video enlarge is redundant.
- Took Lior's recommended option: **dropped `.media-enlarge` + the lightbox video mode** (`#lightbox-vid`,
  `openVid`, `data-fullvid`) — lightbox back to images-only; forum video = plain `controls playsinline`.
- PR **#350** (Closes #338). Suite 1066 passed / 40 skipped locally.
- Issue sweep same day: #331 remaining rows = Lior's tier (his "Next up" on DM thread); #335 closed by Lior
  with final accepted-risk status; #326/#276 blocked on Shiri's model (nothing landed in `ai/`).
