"""Response performance: gzip compression. OWNER: Lior.

Course L7 ("measure, don't guess"; I/O-bound vs CPU-bound): the web tier waits on the DB and the AI
service, so the container runs **gthread** gunicorn workers (concurrency without extra processes — the
network waits release the GIL; see web/Dockerfile). At the response layer we cut bytes on the wire:

* **gzip** (here) the compressible, non-streamed bodies — the big inline-CSS/JS SPA shell and JSON APIs.
* **cache** the static assets — handled Flask-natively via ``SEND_FILE_MAX_AGE_DEFAULT`` (config.py), which
  also gives ETag/conditional-304 revalidation for free.

Both are pure-stdlib (no new dependency). gzip self-skips when it wouldn't help: no ``Accept-Encoding:
gzip``, an already-encoded or streamed (file) response, a non-text type, or a body below the header-overhead
threshold.
"""
import gzip

from flask import request

# Only text-ish types benefit from gzip; PNG icons etc. are already compressed.
_COMPRESSIBLE = {"text/html", "text/css", "text/javascript", "application/javascript",
                 "application/json", "application/manifest+json"}
_MIN_GZIP_BYTES = 500          # below this the ~20-byte gzip header overhead isn't worth the CPU


def init_perf(app):
    """Register the gzip after_request hook on `app`."""

    @app.after_request
    def _compress(response):
        _maybe_gzip(response)
        return response


def _maybe_gzip(response):
    if "gzip" not in request.headers.get("Accept-Encoding", "").lower():
        return
    if response.direct_passthrough:                       # streamed file response -> don't buffer it
        return
    if response.headers.get("Content-Encoding"):          # already encoded (don't double-compress)
        return
    if (response.content_type or "").split(";")[0].strip() not in _COMPRESSIBLE:
        return
    data = response.get_data()
    if len(data) < _MIN_GZIP_BYTES:
        return
    response.set_data(gzip.compress(data, compresslevel=6))   # set_data refreshes Content-Length
    response.headers["Content-Encoding"] = "gzip"
    _add_vary(response, "Accept-Encoding")


def _add_vary(response, value):
    # Caches must key on Accept-Encoding so a gzipped body isn't served to a client that can't decode it.
    existing = response.headers.get("Vary")
    if not existing:
        response.headers["Vary"] = value
    elif value.lower() not in existing.lower():
        response.headers["Vary"] = f"{existing}, {value}"
