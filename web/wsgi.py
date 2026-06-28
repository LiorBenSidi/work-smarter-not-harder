"""Gunicorn entrypoint for the web container. OWNER: Lior.

Configuring logging here (not in ``create_app``) keeps the app factory side-effect-free for tests,
while the real process gets console + rotating-file logging the moment a worker boots. Run by the
Dockerfile: ``gunicorn ... wsgi:app``.
"""
import os

from app import create_app
from logging_config import configure_logging

# Per-worker log file: gunicorn runs multiple workers and RotatingFileHandler is NOT multi-process safe
# (a concurrent rollover from two workers truncates/clobbers the file). Suffix the path with the PID so
# each worker owns its own file; the console handler still aggregates everything for Docker/ELK.
_log_file = os.environ.get("LOG_FILE", "")
if _log_file:
    _base, _ext = os.path.splitext(_log_file)
    _log_file = f"{_base}.{os.getpid()}{_ext}"

configure_logging(log_file=_log_file or None)   # None -> console only (configure reads the empty env)
app = create_app()
