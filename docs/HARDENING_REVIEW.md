# Adversarial Hardening Review

Three independent reviewers audited the app end-to-end (read-only, deliberately blind to the existing
tests so they'd find issues fresh): **auth/session/security**, **forum/DM/data layer**, and the
**front-end SPA**. This document records every finding, its severity, and its status, so the review is
traceable rather than lost in chat history.

**Bottom line:** no authentication bypass, no XSS, no injection (NoSQL `$`-operator payloads are rejected
before any query), no credential/data leak, and no crafted-request crash (a 500 where a 4xx belongs) were
found. The core guards — CSRF double-submit, session-fixation clears, atomic OTP lockout, per-viewer
anonymity, edit/delete authorization, vote integrity, output escaping — all held. Findings are hardening
and robustness improvements.

## Fixed

| ID | Severity | Finding | Fix |
|----|----------|---------|-----|
| FE-1 | HIGH | Every data loader did a bare `await api(...)`; `api()` re-threw on a dropped request, so a network blip left the panel stuck on "Loading…" with an unhandled rejection (realistic on the memory-tight prod VM). | `api()` now returns a synthetic `{ok:false, status:0, data:null}` on network failure, so every caller's existing `!r.ok` branch renders its error fallback. One-place fix covering all loaders + pollers. Guarded by an E2E scenario (force-drop a request → assert error shown, not a spinner). |
| FE-5 | LOW | A failed comment submit was silent (no `else`). | Added an error flash. |
| FE-4 | LOW | The vote ▲/▼ buttons (inline `onclick`, not a `<form>`) bypassed the double-submit guard, so a rapid mash fired N un-awaited requests that could trip the 60/min rate limit. | `voteInFlight` guard on `vote`/`voteComment` + an error flash on a rejected vote. |
| FE-6 | LOW | The landing-orb rAF timer wasn't reset off-screen, so on logout the demo state jumped rather than resuming smoothly. | Reset the timer when the orb is off-screen. |
| (earlier) | HIGH | Forum "can't open a post after voting" wedge — `loadForum` wiped `#forum-list` while `#forum-detail` was slotted inside it, destroying it. | `stashDetail()` before any list wipe + null-box guard in `openPost`. Pinned by a guard test + an E2E regression scenario. |
| (earlier) | HIGH | A failed post-open wedged the forum (stuck `.open` border, no detail). | `failOpen()` clears the half-open state on any failure. Pinned by a guard test + an E2E regression scenario. |
| DATA-D6 | LOW | `vote_comment` returned "comment not found" even when the *post* was missing (the store can't distinguish). | Message is now "post or comment not found" (accurate for both). |
| DATA-D7 | LOW | `_message_shape` / `_notification_shape` hard-accessed `created_at`, which the `$jsonSchema` validator doesn't require → a validator-legal partial write would 500 `/conversations` or `/notifications`. | Use `.get("created_at", 0)` (degrade gracefully, matching the sibling shapes). |
| AUTH-H1 | HIGH | `/forgot-password` timing oracle: a registered email triggered a **synchronous** SMTP send (slow); an unregistered one returned fast — the identical body was defeated by response latency. | The enumeration-sensitive sends now go through `send_email_async`, which offloads the live-SMTP send to a daemon thread → the registered branch returns as fast as the unregistered (no-send) branch. The log backend (dev/CI/grading) stays synchronous (fast, no oracle). Proven by `test_forgot_password_dispatches_the_send_asynchronously` + a unit test that the live send runs off-thread. |
| AUTH-H2 | HIGH | `/register` (verify-on) timing oracle: the code-hash KDF ran only for a fresh email, and its verification email was synchronous — so a duplicate email was distinguishable by latency. | Email now dispatched via `send_email_async` (as H1); the duplicate-email branch runs an **equal-cost dummy KDF** matching the fresh branch's code hash. Both branches now do 2 KDFs + a non-blocking send. Proven by `test_register_equalizes_kdf_work_on_duplicate_email` (KDF-count parity). |

## Accepted / deferred (with rationale)

| ID | Severity | Finding | Disposition |
|----|----------|---------|-------------|
| AUTH-M1 | MED | The registration verify-code attempt counter lives in the (replayable) client session, so the lockout can be rewound. The **login** OTP counter is server-side/atomic and is NOT affected. | **Kept as documented defense-in-depth** — the primary controls fully hold: the code is a fresh random 6-digit value (10⁶ space) with a TTL, and `/register/verify` is capped at **10/min** server-side. Rewinding the *session* attempt counter doesn't lift that rate limit, so an attacker still can't out-guess the code before it expires. A true server-side counter would require a pre-account store keyed by email — which fights the deliberate "no DB row until the email is verified" model (the pending signup lives only in the session). The cost (reintroducing pre-account server state) outweighs the marginal gain over the rate limit; left as-is by design. |
| AUTH-M2 | MED | Account deletion / export omit the media store (no user-scoped media deletion exists). | No media-upload UI is wired, so no user media exists to orphan today. Add a `delete_for_user` + export inclusion when the media UI ships. |
| DATA-D1 | MED | An author can self-upvote; the displayed `score` includes self-votes (the graded engagement metric already excludes them). | Self-voting is a common forum pattern (Reddit auto-upvotes). Aligning `score` with the engagement exclusion is a candidate follow-up; left as-is to avoid a behavior surprise. |
| DATA-D2 | MED | `notification_list` filters `since` in Python after loading the user's full set (per SSE tick + per vote); `message_count_since` loads to count. | Perf/amplification (bounded per-user by an index). Candidate follow-up: push `since` into the query + `count_documents`. |
| DATA-D3 | MED | No pagination/cap on `forum_list_posts` / `notification_list` / conversation reads. | Scale, not correctness. Candidate follow-up: `limit`/cursor. |
| misc LOW | LOW | DM `ref` carries the sender handle; per-worker SSE semaphore; `vote_comment` 404 reason when the post is missing; `created_at` hard-access could 500 on a validator-legal partial write; per-`(actor,ref)` notification coalescing; search-throttle wholesale `.clear()`; stateless-session non-revocation; dev-mode enumeration via `dev_*` fields; per-worker rate-limit; OTP user with no email. | Low severity / documented / non-prod-posture. Tracked here; not blocking. |

## Method

Reviewers were prompted to (1) hunt concrete bugs with severity + repro + fix, and (2) list what they
checked and found clean — so a short clean list couldn't hide a shallow review. Findings acted on were
re-verified against the source before any change, and each fix ships with a test (guard and/or E2E).
