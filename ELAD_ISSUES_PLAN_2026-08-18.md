# ELAD — open-issue plan (2026-08-18)

## Progress

| PR | Issues | State |
|---|---|---|
| #532 | #452, #435 (+3 unreported load-flakes found while verifying) | ✅ **merged** |
| #533 | #507 | ✅ **merged** |
| #534 | #438, #471, #439 | ✅ **merged** |
| #537 | #407 | ✅ **merged** |
| #538 | #408 | ✅ **merged** |
| #539 | scale profile ran `web` on the AI entrypoint | ✅ **merged** (19 Aug) |
| #541 | #434 (bool-as-number on `training_frequency`) | ✅ **merged** (19 Aug) |
| #542 | status sync — PERSON3 / CLAUDE / README | 🟡 open, CI running |

## 19 Aug — deploy recovered

The VM was **powered off** overnight, so both #537's and #539's auto-deploys failed at *Ship compose +
Caddyfile + env to the VM* with `ssh: connect to host … port 22: Connection timed out`. Every test job in
those runs was green — the failure was the host, not the build. Once the VM came back up the failed deploy
job was re-run and went green end to end (ship → pull from GHCR → health check → record last-good SHA;
rollback correctly skipped). Live checks after it: `/ready` → `{"status":"ready"}`, `/auth/config` →
`email_mode: live`, and `…/comments/<cid>/attachments` → **401** (route exists, auth-gated — #407 is live in
prod, not just on main).

**Doc counts reconciled** while resolving #541's conflict with #539: both PRs edited the same test-count
lines. Verified against `pytest --collect-only`, not arithmetic — **1309** = Unit 546 + Integration 464 +
Negative 158 + System 14 + Full-System 27 + Security 88 + Stress 12.

**Runtime verification done for PR-3** (local 3-container stack + real Chrome, not just pytest):
observed network order `POST /media` → `POST /forum/posts` → `POST .../attachments` (#439 proven, not
assumed); tray chips render name/size/thumb/remove; an 11 MB file is blocked before any bytes move and
blocks the send; per-file remove clears correctly; attachment binds and serves 200. The two
`InvalidStateError` console exceptions seen are Lior's #356 view-transition interrupted by scripted
rapid screen-switching — reproduced with **zero** composer code involved, so not a regression here.


Working branch base: `main` @ `1b90900` (synced, `0 0` vs `origin/main`).

Scope = the 8 actionable issues assigned to **@EladNa1**, plus the 3 shared tracking issues.
Everything below ships **branch → PR → CI green → self-merge**; `main` is PR-only and never pushed to directly.

## Decisions taken (user, 2026-08-18)

| Issue | Fork | Chosen |
|---|---|---|
| #439 | publish ordering | **Upload first, then publish** — SPA-side reorder only, no server contract touched |
| #438 + #471 | upload UX depth | **Full composer rework** — managed file array, thumbnails + remove, size pre-check, XHR byte progress, stall timeout, Cancel |
| #407 | comment media | **Implement end-to-end** — routes + UI + tests (TA sub-requirement #2) |

## Non-negotiable gate before every merge

1. `python -m pytest tests/ -q -rf` — full suite green locally (**never** filtered through `grep passed`; #435 documents why).
2. `ruff` + `bandit` via the pre-commit hook; pytest via pre-push.
3. CI green on the PR (ruff · bandit · pytest · `compose-e2e`).
4. Baseline recorded before the first change, compared after the last.

Deploy only happens **after** every PR is merged and `main` is green — auto-deploy fires on green `main` to
`https://app.worksmarternotharder.dev`, then `/ready` + a live smoke check.

---

## PR-1 — test hygiene (zero production risk)

**Closes #452, #435.** Test-only; no app code touched.

- **#452** `tests/Security_Tests/test_ai_queue.py:146` — raw assignment to the *session-cached* `jobqueue`
  module with no undo, held safe only by an unused `client` fixture arg whose monkeypatch teardown restores
  it by accident. Fix: drop the dead `client` param, take `monkeypatch`, use
  `monkeypatch.setattr(jobqueue_module, "_resolve_target", ...)`.
  **Verify the mask is really gone:** the reproduction in the issue is that dropping `client` turns
  `test_jobqueue.py::test_the_worker_target_is_resolved_by_name` red. After the fix, that test must stay
  green with `client` absent.
- **#435** `tests/Unit_Tests/test_bench.py::test_cpu_burn_actually_scales_with_its_work_parameter` — the
  ratio assertion divides by a ~0.7 ms wall-clock window, so one OS scheduling stall fails it (~12 %/run
  under load). Fix: `time.perf_counter()` → `time.process_time()`; keep the `> small * 3` bound.

## PR-2 — media survives account deletion (#507)

Backend + copy. The one store that outlives a deleted account and the one store missing from the export.

1. `web/services/media_store.py` — add an owner-scoped `delete_for_owner(owner)` to **both** `DbMedia` and
   `tests/conftest.py`'s `FakeMedia` (the DI seam must stay mirrored), returning the deleted records so the
   caller can unlink the blobs under `MEDIA_ROOT`.
2. `web/routes/auth.py::delete_account` — add the seventh cascade call, ordered **before** the identity
   record, so a mid-cascade failure leaves a retryable account rather than orphans.
3. `web/routes/auth.py::export_data` — add a `media` key.
4. **Revert the #506 copy** (`web/templates/index.html` ~1280 and ~2065): the export no longer says
   "Uploaded photos and videos aren't included", and the deletion confirmation names seven stores, not six.
   *(#507 calls this out explicitly — closing the gap makes the current honest wording wrong in the other direction.)*
5. Tests: delete-account leaves no media doc **and** no file on disk; export carries media.

## PR-3 — composer rework (#438, #471, #439)

The three are one surface. `#471` forces a managed file array (a real `FileList` cannot have one entry
removed), and once files live in an array the rest of `#438` is cheap.

- **Shared attachment tray**, used by the forum and DM composers (and reused by PR-4's comment composer):
  per-file thumbnail + filename + size + a remove `✕`.
- **Size pre-check** client-side against `MEDIA_MAX_BYTES` before any bytes move (today an oversized file
  uploads to completion on a slow link and only then 413s).
- **`fetch` → `XMLHttpRequest`** — unlocks `upload.onprogress`, and with it: real byte progress
  ("Uploading 2 of 3 · 41 %"), a **stall** timeout (abort only if no bytes move for N s — a *flat* timeout
  would kill a legitimate 10 MB upload on a weak link, ~7 min at 200 kbps), and a working **Cancel**.
- **Picker stays populated when an attach fails**, so retry is one tap (today `picker.value = ""` runs
  regardless of outcome).
- **#439 reorder:** `uploadAll()` runs *before* `POST /forum/posts` / `POST /messages`. A failed upload
  aborts before anything is published, so no photo-less post is ever pushed over SSE and no orphan post
  survives a dead upload.

## PR-4 — comment attachments (#407)

TA Online-Forum sub-requirement #2. The backend is already 90 % there: `media_store` accepts a `"comment"`
target and `media.py:83`'s `_can_view` already handles it — it is **dead code today because nothing writes one**.

- `POST|GET /forum/posts/<pid>/comments/<cid>/attachments` in `web/routes/media.py`, author-gated exactly
  like the post route (`get_comment` → only the comment's author may attach), target id `f"{pid}:{cid}"`.
- Comment composer gets the shared tray from PR-3; attachments render under each comment.
- Tests: attach + serve + the author gate + a non-author 403.
- The four docs that already claim this works (`docs/REPORT.md:317`, `docs/GUIDELINES.md:38`,
  `web/routes/forum.py:5`, `web/routes/media.py:1`) become **true** rather than needing correction.

## PR-5 — attachment-only DM notifies nobody (#408)

TA sub-requirement #5. A DM sent as media with no text produces no notification, no badge, no inbox row and
no SSE push, because attachments bind to the **conversation** (`_dm_key`) and not to a message — so there is
no message to hang a notification on.

Approach: the DM send path creates a message for a media-only send too (so the existing notification,
badge, inbox-row and SSE machinery all fire unchanged), rather than duplicating notification logic into the
media path. This touches the Elad/Lior seam — **flag to Lior on the PR** per the team rule.

## PR-6 — tracking + docs (#434, and status sync for #374 / #400)

- **#434** pre-submission review: confirm every test earns its place (no trivially-passing tests, no test
  that only mirrors the code). Run after all the above so the audit covers the new tests too.
- Sync `PERSON3.md` + `CLAUDE.md`'s status block with what actually shipped.

---

## Deploy (VM is up)

After the last merge and a green `main`:

1. Confirm the auto-deploy pipeline ran (GHCR build → SSH deploy → `/ready` gate, auto-rollback on failure).
2. `curl -fsS https://app.worksmarternotharder.dev/ready`.
3. Live smoke of the changed surfaces: upload a photo, attach one to a **comment**, send a media-only DM and
   confirm the recipient gets a notification, then delete a throwaway account and confirm the media document
   **and** the file on disk are both gone.
4. UptimeRobot monitor `803532626` still green.
