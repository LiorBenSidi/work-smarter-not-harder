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

## 1. Register (email now required)

1. Open http://localhost:8000 → **Register** tab.
2. Username, **Email** (any address — it isn't verified in dev), Password → **Create account**.

The email is stored for password-reset and for the login code. No mailbox needed in dev.

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

## 6. Turn on real email later (optional)

Set an SMTP relay in `.env` (e.g. free Brevo — 300 mails/day) and restart:

```
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USER=<brevo-login>
SMTP_PASS=<brevo-smtp-key>
MAIL_FROM=Work Smarter <no-reply@yourdomain>
```

With `SMTP_HOST` set the code/link go out by email only — the on-screen/log surface turns itself off.

---

## Security notes (how this is built)

- **Codes are stored hashed** (werkzeug), never in plaintext — a DB peek can't reveal a live code.
- **Reset + remember tokens are signed** (`itsdangerous`, time-limited) and embed the password-hash tail,
  so changing the password invalidates outstanding reset links and every trusted browser.
- **The code is bound to the browser session** that requested it (kept in the session, not the request body).
- **CSRF** double-submit + **no username enumeration** on login/forgot + the session cookie stays
  HttpOnly/SameSite (Secure in prod) apply throughout.
