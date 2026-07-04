# Testing the auth (register · 2-step login · remember-this-browser · password reset)

A short, copy-paste guide for anyone — a teammate, the TA, or Noam — to exercise the full auth flow **in
dev / test, without a real mailbox**. We're not in production yet, so email delivery is optional: when no
SMTP server is configured, every code and reset link is **surfaced on screen and written to the logs**.

> **Why it's safe to show the code in dev:** the surface is gated on `SMTP_HOST` being unset. The moment a
> real mail relay is configured (production), the code leaves **only** by email and is never shown or
> returned. See `web/routes/auth.py` → `_issue_otp`.

---

## 0. Run it

```bash
cd work-smarter-not-harder
docker compose up --build -d          # web on http://localhost:8000
# (No SMTP configured by default -> "log backend": codes appear on screen + in the logs.)
```

Watch the logs in another terminal (the code/link is printed here too):

```bash
docker compose logs -f web | grep -i EMAIL
```

---

## 1. Register — now with email verification

1. Open http://localhost:8000 → **Register** tab.
2. Display name, **Email**, Password → **Create account**.
3. You land on a **verification code** screen — the account is **not created until you confirm the code**.
   In **mock** mode (no SMTP) the code is shown right there (*"Dev mode — your code is 123456"*) and in the
   logs; in **live** mode it's emailed. Enter it → the account is created and you're signed straight in.

This stops anyone registering with a fake or someone else's address. The display name can repeat; you sign
in with your **email** (or the display handle). Turn it off for a scripted run with `REGISTER_VERIFY_EMAIL=0`.

---

## Mock ⇄ live, and the dev-tools panel

The single switch for **every** code (login OTP, signup verification, password reset) is **`SMTP_HOST`**:

| Mode | Config | Behaviour |
|---|---|---|
| **Mock** (default for teammates/grading) | `SMTP_HOST` **unset** (no `.env`) | Codes are **shown on screen** + logged. No mailbox needed. |
| **Live** | `SMTP_HOST`/`SMTP_USER`/`SMTP_PASS`/`MAIL_FROM` set (in `.env`) | Codes are **emailed**; never shown or returned. |

**Elad / Shiri:** just run `docker compose up --build` with **no `.env`** → mock mode, every code on-screen.
To go live, add the four `SMTP_*` vars (see the "Real email" steps further down).

**Dev-tools panel:** append **`?debug=1`** to the URL → a **⚙ button appears bottom-right** (only in debug
mode). It opens a panel to **preview the mobile layout in a desktop browser** (Desktop/Mobile) and shows the
current **email mode** (MOCK/LIVE). Zero footprint in normal use; "Disable dev tools" turns it off.

## 1b. Password reset (dev)

**Forgot your password?** → enter your email → in mock mode the reset link is **shown on screen** as
*"open reset link (dev)"* (and logged); in live mode it's emailed. Click it → set a new password.

## 2. Log in — the 6-digit code (2-step verification)

1. **Log in** tab → username + password → **Log in**.
2. You land on the **Verification code** screen. In dev the code is shown right there:
   *"Dev mode — your code is 123456"* — and also in `docker compose logs web` (`EMAIL (log backend) …`).
3. Enter the code → **Verify & sign in**. You're in.

The code **expires in 10 min** and **locks out after 5 wrong tries** (then just log in again for a fresh one).

## 3. "Trust this browser" (skip the code next time)

- On the code screen, tick **Trust this browser for 30 days** before verifying.
- Next login on the *same* browser skips the code entirely.
- Trust is revoked automatically by **logging out**, by a **password change/reset**, or by clearing cookies —
  and a *different* user logging in on that browser still gets prompted. Leave it unticked to be asked every time.

## 4. Forgot / reset password

1. **Log in** tab → **Forgot your password?** → enter your email → **Send reset link**.
2. In dev the reset link is in the logs (`EMAIL (log backend) …`); open it. It carries a `?reset_token=…`
   that lands you on the **Set new password** screen.
3. Set a new password → log in with it. (The old link is single-use and stops working once the password changes.)

---

## 5. Automated tests (no Docker needed)

```bash
python -m pytest tests/Unit_Tests/test_email.py \
                 tests/Integration_Tests/test_password_reset.py \
                 tests/Integration_Tests/test_login_otp.py -v
```

`test_login_otp.py` runs with OTP **on** (the app's normal login tests keep the one-step flow via the
`TESTING` gate, so both are covered).

---

## 6. Go live with real email (Brevo — free, 300 mails/day)

The whole sending path is already built and tested; going live is **provider config only** — no code
change. Brevo is the pick (300/day free, no time limit; SendGrid free is 100/day).

1. **Create a free Brevo account** at <https://www.brevo.com> (this step is yours — it needs a login).
2. **Verify a sender:** Brevo → *Senders, Domains & Dedicated IPs → Senders → Add a sender*, then click
   the confirmation link Brevo emails you. `MAIL_FROM` **must** be this verified address or the relay
   rejects the send.
3. **Get the SMTP key:** Brevo → *SMTP & API → SMTP*. Note your **login** (an email) and **Generate a new
   SMTP key**.
4. **Put them in `.env`** (gitignored — never commit real keys):
   ```
   SMTP_HOST=smtp-relay.brevo.com
   SMTP_PORT=587
   SMTP_USER=<your-brevo-login-email>
   SMTP_PASS=<the-generated-smtp-key>
   MAIL_FROM=Work Smarter <your-verified-sender@domain>
   ```
5. **Verify delivery with one command** (no need to run the whole app):
   ```bash
   docker compose up -d
   docker compose exec web python scripts/send_test_email.py --to liortestbase@proton.me
   # local (outside Docker): python web/scripts/send_test_email.py --to you@example.com   (with the env set)
   ```
   Exit `0` + a message in the inbox = you're live. Exit `1` = check the key / verified sender (the script
   says which).
6. **Restart the stack.** With `SMTP_HOST` set, the login OTP + reset links now go out **by email only** —
   the dev on-screen/log surface turns itself off automatically.

> **Deploy note (Azure):** some clouds block outbound port **587**. If the test send hangs/fails on the VM
> but works locally, that's the port — open 587 egress on the VM, or switch to Brevo's HTTP API (a small
> swap in `web/services/email.py`; stdlib `requests` is already a dependency).

---

## Security notes (how this is built)

- **Codes are stored hashed** (werkzeug), never in plaintext — a DB peek can't reveal a live code.
- **Reset + remember tokens are signed** (`itsdangerous`, time-limited) and embed the password-hash tail,
  so changing the password invalidates outstanding reset links and every trusted browser.
- **The code is bound to the browser session** that requested it (kept in the session, not the request body).
- **CSRF** double-submit + **no username enumeration** on login/forgot + the session cookie stays
  HttpOnly/SameSite (Secure in prod) apply throughout.
