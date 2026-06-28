"""Gunicorn entrypoint for the web container. OWNER: Lior.

Configuring logging here (not in ``create_app``) keeps the app factory side-effect-free for tests,
while the real process gets console + rotating-file logging the moment a worker boots. Run by the
Dockerfile: ``gunicorn ... wsgi:app``.

Import order matters: configure logging BEFORE create_app so the factory's own boot warnings (e.g. the
ephemeral-SECRET_KEY notice) are formatted by our handlers, not the unformatted last-resort handler.
"""
import os
import sys

from app import create_app
from logging_config import configure_logging, worker_log_file

# Per-worker log file: gunicorn runs multiple workers and RotatingFileHandler is NOT multi-process safe
# (a concurrent rollover from two workers clobbers the file), so each worker writes its own PID-suffixed
# file. NOTE: with worker recycling (--max-requests, crashes, redeploys) old per-PID files accumulate;
# the console handler is the primary container sink (Docker/ELK), and the file family is best-effort — a
# long-running deployment should sweep stale `*.<pid>.log*` (or rely on console only).
_log_file = os.environ.get("LOG_FILE", "")
if _log_file:
    try:
        _log_file = worker_log_file(_log_file, os.getpid())
    except ValueError as exc:
        # a misconfigured LOG_FILE (e.g. a directory) must not crash the user-facing container. Logging
        # isn't configured yet here, so write straight to stderr (Docker captures it).
        sys.stderr.write(f"[wsgi] {exc} — falling back to console logging\n")
        _log_file = ""

configure_logging(log_file=_log_file or None)   # None -> console only (configure reads the empty env)
app = create_app()
