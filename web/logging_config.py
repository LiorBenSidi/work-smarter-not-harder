"""Application logging setup — Week 9 / Lab 9.1 (print -> logging). OWNER: Lior.

Every module already uses ``logging.getLogger(__name__)`` (named-logger-per-module). This wires the
*output*: a console handler (so gunicorn/Docker capture it on stdout/stderr) plus an optional rotating
file handler, attached once to the root logger. Level and on/off come from the environment, so prod,
dev and tests differ by configuration — not by code:

    ENABLE_LOGGING=0   -> logging suppressed entirely — a dev/benchmark "cost" toggle (Lab-9.1). NOTE:
                          this calls logging.disable(CRITICAL), which silences EVERY logger in the
                          process (incl. library/gunicorn CRITICALs) — diagnostics-blind; never prod.
    LOG_LEVEL=DEBUG    -> verbose; default INFO
    LOG_FILE=/path     -> also write a RotatingFileHandler there; empty (default) = console only

Kept out of ``create_app`` so the test suite stays quiet: the gunicorn entrypoint (``wsgi.py``)
configures logging, the app factory only registers the per-request access log.
"""
import logging
import os
from logging.handlers import RotatingFileHandler

_FMT = "%(asctime)s %(levelname)-7s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_MANAGED = "_ws_managed"          # marks the handlers WE own, so we never stomp gunicorn's/pytest's
_MAX_BYTES = 1_000_000
_BACKUPS = 3


def _truthy(value):
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_level(level):
    """Map a level name ('DEBUG') or int to a logging constant; unknown names fall back to INFO."""
    if isinstance(level, int):
        return level
    return getattr(logging, str(level).upper(), logging.INFO)


def worker_log_file(log_file, pid):
    """Return a per-worker log path: insert `pid` before the extension.

    gunicorn runs several workers and ``RotatingFileHandler`` is not multi-process safe, so each worker
    must own its own file. A missing extension defaults to ``.log`` (so ELK ``*.log`` globs still match),
    and a directory target is refused (raise) rather than silently writing a hidden dotfile or a sibling.
    """
    if not log_file:
        return log_file
    if log_file.endswith(("/", os.sep)) or os.path.isdir(log_file):
        raise ValueError(f"LOG_FILE must be a file path, not a directory: {log_file!r}")
    base, ext = os.path.splitext(log_file)
    return f"{base}.{pid}{ext or '.log'}"


def configure_logging(*, level=None, enable=None, log_file=None, force=False):
    """Wire root logging once: console + optional rotating file. Returns the root logger.

    Each kwarg falls back to its env var when None (ENABLE_LOGGING / LOG_LEVEL / LOG_FILE). Idempotent:
    our handlers are tagged ``_ws_managed`` and the call is a no-op if they're already present — pass
    ``force=True`` (tests) to tear them down and re-apply with different settings.
    """
    root = logging.getLogger()
    managed = [h for h in root.handlers if getattr(h, _MANAGED, False)]
    if managed and not force:
        return root
    for handler in managed:                       # force=True: drop our old handlers, keep others'
        root.removeHandler(handler)
        handler.close()

    if enable is None:
        enable = _truthy(os.environ.get("ENABLE_LOGGING", "1"))
    if not enable:
        logging.disable(logging.CRITICAL)         # make every logging call a near-no-op (measure cost)
        return root
    logging.disable(logging.NOTSET)               # undo a prior disable (e.g. a test that turned it off)

    if level is None:
        level = os.environ.get("LOG_LEVEL", "INFO")
    root.setLevel(_resolve_level(level))

    formatter = logging.Formatter(_FMT, datefmt=_DATEFMT)

    console = logging.StreamHandler()             # -> stderr; Docker/gunicorn capture it
    console.setFormatter(formatter)
    setattr(console, _MANAGED, True)
    root.addHandler(console)

    if log_file is None:
        log_file = os.environ.get("LOG_FILE", "")
    if log_file:
        try:
            parent = os.path.dirname(log_file)
            if parent:
                os.makedirs(parent, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_file, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            setattr(file_handler, _MANAGED, True)
            root.addHandler(file_handler)
        except OSError:
            # A missing/read-only log dir must never crash the app — console logging still works. Logged
            # at ERROR (not warning) so an operator who configured LOG_FILE notices the audit log is gone.
            root.error("file logging disabled — cannot open %s", log_file, exc_info=True)

    return root
