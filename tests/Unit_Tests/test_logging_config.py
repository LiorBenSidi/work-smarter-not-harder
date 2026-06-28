"""Unit tests for web/logging_config.py — the Week-9 / Lab-9.1 logging wiring. OWNER: Lior.

Logging state is process-global, so the `isolated_root_logger` fixture snapshots the root logger's
handlers / level / global-disable and restores them after each test — these never leak into the rest
of the suite. configure_logging() is loaded off disk (web/ isn't an installed package).
"""
import importlib.util
import logging
import os
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"


@pytest.fixture
def logmod():
    spec = importlib.util.spec_from_file_location("web_logging_under_test", str(WEB / "logging_config.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def isolated_root_logger():
    """Snapshot + restore the global logging state so a test can reconfigure it freely."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    saved_disable = logging.root.manager.disable
    try:
        yield root
    finally:
        for h in root.handlers[:]:
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)
        logging.disable(saved_disable)


def _managed(root):
    return [h for h in root.handlers if getattr(h, "_ws_managed", False)]


def test_adds_a_single_console_handler(logmod, isolated_root_logger):
    root = logmod.configure_logging(enable=True, level="INFO", log_file="", force=True)
    managed = _managed(root)
    assert len(managed) == 1
    assert isinstance(managed[0], logging.StreamHandler)


def test_level_is_applied(logmod, isolated_root_logger):
    logmod.configure_logging(enable=True, level="WARNING", log_file="", force=True)
    assert logging.getLogger().level == logging.WARNING


def test_unknown_level_falls_back_to_info(logmod, isolated_root_logger):
    logmod.configure_logging(enable=True, level="NONSENSE", log_file="", force=True)
    assert logging.getLogger().level == logging.INFO


def test_enable_false_suppresses_logging_and_adds_no_handler(logmod, isolated_root_logger):
    root = logmod.configure_logging(enable=False, force=True)
    assert logging.root.manager.disable == logging.CRITICAL   # the Lab-9.1 cost toggle
    assert _managed(root) == []                               # nothing attached when off


def test_idempotent_without_force(logmod, isolated_root_logger):
    logmod.configure_logging(enable=True, log_file="", force=True)
    logmod.configure_logging(enable=True, log_file="")        # no force -> no-op
    assert len(_managed(logging.getLogger())) == 1


def test_force_replaces_handlers_without_stacking(logmod, isolated_root_logger):
    logmod.configure_logging(enable=True, level="INFO", log_file="", force=True)
    logmod.configure_logging(enable=True, level="DEBUG", log_file="", force=True)
    assert len(_managed(logging.getLogger())) == 1            # replaced, not duplicated
    assert logging.getLogger().level == logging.DEBUG


def test_rotating_file_handler_writes_and_creates_parent(logmod, isolated_root_logger, tmp_path):
    from logging.handlers import RotatingFileHandler
    log_file = tmp_path / "nested" / "web.log"               # parent dir must be auto-created
    root = logmod.configure_logging(enable=True, level="INFO", log_file=str(log_file), force=True)
    managed = _managed(root)
    assert any(isinstance(h, RotatingFileHandler) for h in managed)
    assert len(managed) == 2                                  # console + file
    logging.getLogger("test.logging.sink").info("hello-from-test")
    for h in managed:
        h.flush()
    assert "hello-from-test" in log_file.read_text()


def test_bad_log_path_is_swallowed_console_still_works(logmod, isolated_root_logger):
    bad = os.path.join("/dev/null", "cannot", "web.log")     # mkdir under a file -> OSError
    root = logmod.configure_logging(enable=True, log_file=bad, force=True)
    # the failure is swallowed: the console handler is still attached and no exception propagated
    assert any(isinstance(h, logging.StreamHandler) and getattr(h, "_ws_managed", False)
               for h in root.handlers)


def test_re_enabling_clears_a_prior_disable(logmod, isolated_root_logger):
    logmod.configure_logging(enable=False, force=True)
    assert logging.root.manager.disable == logging.CRITICAL
    logmod.configure_logging(enable=True, log_file="", force=True)
    assert logging.root.manager.disable == logging.NOTSET     # turned back on


def test_request_emits_access_log_with_timing(make_client, fake_users, caplog):
    # the app factory's after_request access log fires on a real request (web/app.py)
    client = make_client(fake_users)
    with caplog.at_level(logging.INFO):
        client.get("/health")
    msgs = [r.getMessage() for r in caplog.records]
    assert any("/health" in m and "->" in m and "ms" in m for m in msgs)


def test_access_log_sanitizes_crlf_in_path(make_client, fake_users, caplog):
    # a CRLF-bearing path must NOT produce a raw newline in the log line (CWE-117 log forging)
    client = make_client(fake_users)
    with caplog.at_level(logging.INFO):
        client.get("/foo%0d%0afake-log-line")
    line = next((r.getMessage() for r in caplog.records if "foo" in r.getMessage()), "")
    assert line, "expected an access-log line for the request"
    assert "\n" not in line and "\r" not in line     # no raw CR/LF -> no forged second line
    assert "\\r" in line or "\\n" in line             # the control chars were escaped, not dropped silently


def test_disabled_then_enabled_without_force_recovers(logmod, isolated_root_logger):
    # refutes the adversarial "stuck-mute" claim: disabling then re-enabling restores logging even
    # WITHOUT force=True — the disabled branch attaches no managed handler, so the next enable=True
    # never hits the idempotency early-return and reaches logging.disable(NOTSET).
    logmod.configure_logging(enable=False)                  # no force
    assert logging.root.manager.disable == logging.CRITICAL
    logmod.configure_logging(enable=True, log_file="")      # no force
    assert logging.root.manager.disable == logging.NOTSET   # recovered, not stuck-muted
    assert _managed(logging.getLogger())                    # console handler attached
