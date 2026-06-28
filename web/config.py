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
