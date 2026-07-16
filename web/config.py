"""Env-driven config — no secrets in code (real values come from .env; see .env.example)."""
import os


def _int_env(name, default):
    """Parse a positive int env var; fall back to `default` on a missing/garbage/<=0 value.

    Runs at import time, so a typo (e.g. MAX_CONTENT_LENGTH=64kb) must NOT raise — that would kill
    the worker on startup. Degrade to the safe default instead.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "")          # required in real runs (set via .env)
    MONGO_URI = os.environ.get("MONGO_URI", "mongodb://db:27017/worksmarter")
    AI_URL = os.environ.get("AI_URL", "http://ai:5000")
    # How long web waits for ai `/predict` before degrading. INTERIM value: must stay >= the ai queue's
    # AI_PREDICT_TIMEOUT_SECONDS (default 30) so web doesn't give up on — and discard — a result ai is
    # still computing. Re-tune (likely down) once the real model's predict-time is measured (PERSON1.md).
    AI_CLIENT_TIMEOUT = _int_env("AI_CLIENT_TIMEOUT_SECONDS", 33)
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    TESTING = os.environ.get("TESTING", "0") == "1"
    # Per-IP rate limiting (flask-limiter). ON by default (prod-safe). Env-gated so the browser-E2E stack can
    # turn it OFF (RATELIMIT_ENABLED=0): that suite registers a fresh user per scenario, which legitimately
    # exceeds the anti-abuse caps and would 429 — the caps themselves are covered by test_rate_limit.py.
    RATELIMIT_ENABLED = os.environ.get("RATELIMIT_ENABLED", "1") == "1"

    # Session-cookie hardening. HttpOnly + SameSite=Lax are always on; Secure is env-gated so local
    # dev + the HTTP test client work out of the box — set SESSION_COOKIE_SECURE=1 in production (HTTPS).
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    # Cap request bodies (auth/profile are small JSON) -> a huge body is rejected (413) before parsing.
    MAX_CONTENT_LENGTH = _int_env("MAX_CONTENT_LENGTH", 64 * 1024)

    # Static-asset caching (perf, course L7): Flask's send_file stamps the icons/manifest with
    # `Cache-Control: public, max-age=<n>` + an ETag, so repeat visits revalidate cheaply (304) or skip
    # the round-trip entirely. The served HTML shell is render_template (not a file send) -> uncached, so
    # UI updates ship immediately; sw.js overrides to no-cache in its route so the SW keeps updating.
    SEND_FILE_MAX_AGE_DEFAULT = _int_env("SEND_FILE_MAX_AGE_DEFAULT", 86400)   # 24h

    # Email (OTP + password reset). No SMTP_HOST -> the log backend (dev): the message is logged and
    # nothing leaves the box. Set SMTP_HOST/USER/PASS in .env to send real mail (STARTTLS, default :587).
    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = _int_env("SMTP_PORT", 587)
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASS = os.environ.get("SMTP_PASS", "")
    SMTP_STARTTLS = os.environ.get("SMTP_STARTTLS", "1") == "1"
    MAIL_FROM = os.environ.get("MAIL_FROM", "Work Smarter, Not Harder <no-reply@worksmarter.local>")
    # Public base URL used to build the password-reset link in emails (the deploy sets its real domain).
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")
    # DEV-ONLY email-mock override. When ON, a request carrying `X-Debug-Email: mock` is served the log
    # backend even where SMTP is configured: the auth code is RETURNED in the JSON response instead of
    # emailed, so a developer can test signup/login/reset on a live-SMTP deploy without a real inbox
    # (driven by the gated toggle in the debug-tools panel). OFF by default and IGNORED under TESTING.
    # NEVER enable on a public deployment — it lets any caller pull the OTP for any address (account
    # takeover). Flip it on only while YOU personally test, then off for the demo.
    AUTH_DEBUG_EMAIL = os.environ.get("AUTH_DEBUG_EMAIL", "0") == "1"
    # Signed-token lifetimes (seconds): password-reset link and (PR-C) the login OTP.
    RESET_TOKEN_MAX_AGE = _int_env("RESET_TOKEN_MAX_AGE", 600)      # 10 min — a stale reset link (old email) can't reset; matches the OTP window
    # 2-step verification (email OTP on login). On by default in real runs; the test suite turns it off
    # (see the login route) so the existing username+password login tests stay valid.
    OTP_ENABLED = os.environ.get("OTP_ENABLED", "1") == "1"
    OTP_TTL_SECONDS = _int_env("OTP_TTL_SECONDS", 600)             # 10 min
    OTP_MAX_ATTEMPTS = _int_env("OTP_MAX_ATTEMPTS", 5)
    # Email verification at registration: email a code and only create the account once it's confirmed, so a
    # user can't register with a fake or someone else's address. On by default in real runs; TESTING turns it
    # off (see the register route) so the existing register-then-login tests stay valid. Reuses OTP_TTL/ATTEMPTS.
    REGISTER_VERIFY_EMAIL = os.environ.get("REGISTER_VERIFY_EMAIL", "1") == "1"
    # Opt-in "remember this browser" cookie: how long a browser stays trusted (skips the login OTP)
    # before it must re-verify. Invalidated early by a password change (embedded hash tail) or logout.
    REMEMBER_COOKIE_MAX_AGE = _int_env("REMEMBER_COOKIE_MAX_AGE", 30 * 24 * 3600)   # 30 days

    # Forum/DM media attachments (OWNER: Elad). Bytes are stored on a web-mounted volume at MEDIA_ROOT;
    # MEDIA_MAX_BYTES caps a single upload (enforced per-request in the media route, so the small
    # MAX_CONTENT_LENGTH above still guards the JSON routes); only the allowlisted MIME types are accepted.
    MEDIA_ROOT = os.environ.get("MEDIA_ROOT", "/app/media")
    MEDIA_MAX_BYTES = _int_env("MEDIA_MAX_BYTES", 10 * 1024 * 1024)   # 10 MB per file
    # Volume-wide cap (issue #313): once MEDIA_ROOT holds this many bytes, further uploads 507 — so an
    # authenticated flood can't fill the VM's disk 10 MB at a time (a full disk wedges Mongo + logging).
    MEDIA_MAX_TOTAL_BYTES = _int_env("MEDIA_MAX_TOTAL_BYTES", 500 * 1024 * 1024)   # 500 MB total
    MEDIA_ALLOWED_MIME = os.environ.get(
        "MEDIA_ALLOWED_MIME", "image/png,image/jpeg,image/webp,image/gif,video/mp4")
