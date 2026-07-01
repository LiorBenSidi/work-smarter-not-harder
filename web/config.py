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
    DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"
    TESTING = os.environ.get("TESTING", "0") == "1"

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
    MAIL_FROM = os.environ.get("MAIL_FROM", "Work Smarter <no-reply@worksmarter.local>")
    # Public base URL used to build the password-reset link in emails (the deploy sets its real domain).
    APP_BASE_URL = os.environ.get("APP_BASE_URL", "http://localhost:8000")
    # Signed-token lifetimes (seconds): password-reset link and (PR-C) the login OTP.
    RESET_TOKEN_MAX_AGE = _int_env("RESET_TOKEN_MAX_AGE", 1800)     # 30 min
    # 2-step verification (email OTP on login). On by default in real runs; the test suite turns it off
    # (see the login route) so the existing username+password login tests stay valid.
    OTP_ENABLED = os.environ.get("OTP_ENABLED", "1") == "1"
    OTP_TTL_SECONDS = _int_env("OTP_TTL_SECONDS", 600)             # 10 min
    OTP_MAX_ATTEMPTS = _int_env("OTP_MAX_ATTEMPTS", 5)
    # Opt-in "remember this browser" cookie: how long a browser stays trusted (skips the login OTP)
    # before it must re-verify. Invalidated early by a password change (embedded hash tail) or logout.
    REMEMBER_COOKIE_MAX_AGE = _int_env("REMEMBER_COOKIE_MAX_AGE", 30 * 24 * 3600)   # 30 days
