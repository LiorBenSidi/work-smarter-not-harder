# Email deliverability — the 16-July demo failure, investigated

**TL;DR.** During the 16-July demo, login codes arrived minutes late and mostly didn't work. Two
separate things combined:

1. **Deterministic (our code, now fixed):** every `POST /login` minted a *new* OTP that *overwrote* the
   previous one, so a burst of logins left only the *last* code valid. All the earlier codes people
   received were already dead.
2. **Transient (Brevo free tier, not reproducible):** that morning Brevo held our burst of emails ~2–8
   min and released them in a single batch. This is real but was a one-off — two deliberate
   reproductions the same afternoon delivered in 1–3 s and could not trigger it again.

The fix in this repo addresses #1. #2 is a provider/ops matter (see the bottom).

## How we know (evidence)

The app logs `EMAIL (smtp) sent to=…` the instant Brevo's relay *accepts* a message. Brevo's own
transactional log records when Brevo *dispatched* it (`Sent`) and when the recipient MX *accepted* it
(`Delivered`). Comparing the app log (UTC) against Brevo's log (Israel time, UTC+3) for the demo window:

| App handed to Brevo (IDT) | Brevo dispatched (`Sent`) | Held for | Recipient |
|---|---|---|---|
| 09:22:51 | 09:30:46 | **7m 55s** | lior login code |
| 09:23:06 | 09:30:46 | **7m 40s** | elad login code |
| 09:23:21 | 09:30:46 | **7m 25s** | lior login code |
| 09:24:44 | 09:30:46 | **6m 02s** | lior login code |
| 09:25:18 | 09:30:46 | **5m 28s** | lior login code |
| 09:28:13 | 09:30:46 | **2m 33s** | elad login code |
| 09:28:32 | 09:30:46 | **2m 14s** | lior login code |

Seven codes handed over across ~6 min, all **released together at 09:30:46** — a batch hold. Single
messages before and after went out in ~1 s. Once Brevo *dispatches*, delivery to Gmail is fast:
`Sent`→`Delivered` was median **1 s, max 4 s** across 58 messages. So the ~10-min delay lived entirely in
the **app-handoff → Brevo-dispatch** leg, which Brevo's `Sent`→`Delivered` column can't show.

### Reproduction (same day, ~3 h later)

- **6× `/forgot-password`** over 78 s → all dispatched in **1–3 s**. No hold.
- **6× `/login`** (the exact demo path, synchronous send) over 90 s → all dispatched in **~2 s**. No hold.

Neither reproduced the batch hold, despite being *denser* than the demo. Conclusion: the hold was a
transient Brevo free-tier condition (new domain, first real traffic spike from the class), **not** a
deterministic rate rule and **not** an app bug.

### The invalidation, reproduced live

With OTP live, six rapid `/login`s were fired, then `/verify-otp` was called with two of the codes:

- an earlier code → `{"error":"incorrect code"}`
- the newest code → `{"status":"logged in"}`

Two codes, same inbox, same burst — only the last-issued one works. That is the deterministic mechanism.

## The fix (this change)

`web/routes/auth.py` — new helper `_ensure_login_otp`. In **live-SMTP mode**, if a still-valid,
unexpired, unlocked login code already exists for the user, `/login` **reuses** it instead of minting a
new one: no new email, `code_sent=False`, and `expires_in` reports the *remaining* time. The code from the
email the user already has stays valid. A burst of logins → **one code, one email**.

- Reuse preserves the existing expiry and wrong-guess attempt counter (a re-login can't reset the lockout
  clock or extend the window). It skips a locked slot (`attempts >= OTP_MAX_ATTEMPTS`) and re-mints instead.
- If a live send *fails*, the stored challenge is cleared, so the next login re-mints and re-sends
  (reuse never locks onto a code the user never received).
- **Dev / no-SMTP** mode always mints fresh (it surfaces the code in the response for grading) — unchanged.
- `/resend-otp` still always mints a fresh code — the explicit "I didn't get it" escape hatch.

UI: the OTP screen shows *"You already have a valid code in your email … tap Resend if you need a fresh
one"* when a code was reused, so a rapid repeat reads as intended behaviour, not a broken mailer.

Tests: `tests/Integration_Tests/test_login_otp_reuse.py` (reuse-sends-one-email, reused-code-verifies,
expired→re-mint, attempt-counter-preserved, locked→re-mint, failed-send→re-attempt, dev-always-fresh,
resend-always-fresh). Cross-checked by an independent test writer (8/8, blind to the impl) and an
adversarial reviewer (no critical/high; the OTP branch is behind the password check). Suite is
mutation-tested — 6/6 seeded mutations killed.

## Ops notes (not code)

- **Brevo free tier** (~300 emails/day + a burst rate limit) is a real constraint now that the app link
  was shared to the whole course. The reuse fix sharply cuts login-email volume, which is the main lever
  we control. If delivery delays recur under load, the remaining lever is the Brevo plan/rate — check the
  dashboard's daily counter and sending limits.
- **`AUTH_DEBUG_EMAIL` must stay OFF.** With real users on the app, the on-screen-code mock is an
  account-takeover exposure. It's off by default and ignored under tests; do not enable it in production.
- Verified fine and unchanged: SPF / DKIM (brevo1, brevo2) / DMARC all valid; domain verified;
  `Sent`→`Delivered` ~1 s.
