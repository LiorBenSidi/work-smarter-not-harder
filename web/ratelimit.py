"""App-wide rate limiting (anti-spam / anti-brute-force) via flask-limiter.

Created unbound here and wired in ``app.py`` (mirrors ``csrf.py``); sensitive routes opt in with
``@limiter.limit(...)``. Only the auth routes are limited — the app's normal traffic (dashboard,
notification polling, the SSE stream) is left alone, so no legitimate use is throttled.

Storage is in-memory (per-process) — fine for the single-process demo/preview. A multi-worker
deployment should point ``RATELIMIT_STORAGE_URI`` at a shared backend (redis/memcached) so the limit
is enforced across workers; with in-memory storage each worker counts independently (still a real cap,
just N× looser). The limiter is a no-op whenever ``RATELIMIT_ENABLED`` is false (the test suite sets
that so its many rapid login/register calls aren't throttled); the request-filter reads it per request.
"""
from flask import current_app
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# key = client IP. No default limits: routes opt in individually.
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")


@limiter.request_filter
def _rate_limit_exempt():
    # Evaluated per request, so tests can toggle RATELIMIT_ENABLED after app creation and it takes
    # effect immediately. Default on (production/preview); tests set it off.
    return not current_app.config.get("RATELIMIT_ENABLED", True)


def init_limiter(app):
    app.config.setdefault("RATELIMIT_STORAGE_URI", "memory://")
    limiter.init_app(app)
