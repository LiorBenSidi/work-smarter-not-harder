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
    """Turning logging on attaches exactly one console handler, so every record appears once instead of being duplicated per attached handler."""
    root = logmod.configure_logging(enable=True, level="INFO", log_file="", force=True)
    managed = _managed(root)
    assert len(managed) == 1
    assert isinstance(managed[0], logging.StreamHandler)


def test_level_is_applied(logmod, isolated_root_logger):
    """The configured level is genuinely applied, so raising it in production actually silences the quieter records rather than only appearing to."""
    logmod.configure_logging(enable=True, level="WARNING", log_file="", force=True)
    assert logging.getLogger().level == logging.WARNING


def test_unknown_level_falls_back_to_info(logmod, isolated_root_logger):
    """A typo in the level name falls back to a usable default instead of leaving the app running with no logging at all."""
    logmod.configure_logging(enable=True, level="NONSENSE", log_file="", force=True)
    assert logging.getLogger().level == logging.INFO


def test_enable_false_suppresses_logging_and_adds_no_handler(logmod, isolated_root_logger):
    """The off switch both suppresses records AND attaches nothing, so the cost of logging can be measured against a genuinely quiet baseline."""
    root = logmod.configure_logging(enable=False, force=True)
    assert logging.root.manager.disable == logging.CRITICAL   # the Lab-9.1 cost toggle
    assert _managed(root) == []                               # nothing attached when off


def test_idempotent_without_force(logmod, isolated_root_logger):
    """Configuring twice does not stack a second handler, so an accidental re-entry cannot silently double every log line."""
    logmod.configure_logging(enable=True, log_file="", force=True)
    logmod.configure_logging(enable=True, log_file="")        # no force -> no-op
    assert len(_managed(logging.getLogger())) == 1


def test_force_replaces_handlers_without_stacking(logmod, isolated_root_logger):
    """A forced reconfigure replaces the handler rather than adding to it, and the new level takes effect — so logging can be re-tuned at runtime without growing a handler per call."""
    logmod.configure_logging(enable=True, level="INFO", log_file="", force=True)
    logmod.configure_logging(enable=True, level="DEBUG", log_file="", force=True)
    assert len(_managed(logging.getLogger())) == 1            # replaced, not duplicated
    assert logging.getLogger().level == logging.DEBUG


def test_rotating_file_handler_writes_and_creates_parent(logmod, isolated_root_logger, tmp_path):
    """Pointing at a log file attaches a rotating file handler alongside the console, creates the parent directory that does not exist yet, and the records genuinely arrive in the file."""
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
    """An unusable log path must not take the app down: the failure is swallowed and console logging keeps working."""
    bad = os.path.join("/dev/null", "cannot", "web.log")     # mkdir under a file -> OSError
    root = logmod.configure_logging(enable=True, log_file=bad, force=True)
    # the failure is swallowed: the console handler is still attached and no exception propagated
    assert any(isinstance(h, logging.StreamHandler) and getattr(h, "_ws_managed", False)
               for h in root.handlers)


def test_re_enabling_clears_a_prior_disable(logmod, isolated_root_logger):
    """Turning logging back on genuinely clears an earlier suppression, so a process cannot end up permanently muted."""
    logmod.configure_logging(enable=False, force=True)
    assert logging.root.manager.disable == logging.CRITICAL
    logmod.configure_logging(enable=True, log_file="", force=True)
    assert logging.root.manager.disable == logging.NOTSET     # turned back on


def test_request_emits_access_log_with_timing(make_client, fake_users, caplog):
    """A real request produces an access line carrying the path and how long it took — the record that makes a slow endpoint visible at all."""
    # the app factory's after_request access log fires on a real request (web/app.py)
    client = make_client(fake_users)
    with caplog.at_level(logging.INFO):
        client.get("/health")
    msgs = [r.getMessage() for r in caplog.records]
    assert any("/health" in m and "->" in m and "ms" in m for m in msgs)


def test_access_log_sanitizes_crlf_in_path(make_client, fake_users, caplog):
    """A path containing CR/LF must not put a raw newline in the log, or an attacker could forge a second, entirely fabricated log line.

    The characters are escaped rather than silently dropped, so the attempt itself stays visible to whoever reads the log.
    """
    client = make_client(fake_users)
    with caplog.at_level(logging.INFO):
        client.get("/foo%0d%0afake-log-line")
    line = next((r.getMessage() for r in caplog.records if "foo" in r.getMessage()), "")
    assert line, "expected an access-log line for the request"
    assert "\n" not in line and "\r" not in line     # no raw CR/LF -> no forged second line
    assert "\\r" in line or "\\n" in line             # the control chars were escaped, not dropped silently


def test_disabled_then_enabled_without_force_recovers(logmod, isolated_root_logger):
    """Disabling and then re-enabling restores logging even WITHOUT forcing, so a process cannot get stuck permanently muted by an ordinary pair of calls."""
    # refutes the adversarial "stuck-mute" claim: disabling then re-enabling restores logging even
    # WITHOUT force=True — the disabled branch attaches no managed handler, so the next enable=True
    # never hits the idempotency early-return and reaches logging.disable(NOTSET).
    logmod.configure_logging(enable=False)                  # no force
    assert logging.root.manager.disable == logging.CRITICAL
    logmod.configure_logging(enable=True, log_file="")      # no force
    assert logging.root.manager.disable == logging.NOTSET   # recovered, not stuck-muted
    assert _managed(logging.getLogger())                    # console handler attached


# ---- worker_log_file (per-worker path) — adversarial round 2 (F3) ----
def test_worker_log_file_inserts_pid_before_extension(logmod):
    """Each worker writes to its own file, so several processes cannot interleave and corrupt one another's lines."""
    assert logmod.worker_log_file("/app/logs/web.log", 123) == "/app/logs/web.123.log"


def test_worker_log_file_defaults_missing_extension_to_log(logmod):
    """A path with no extension still gets one, so the log-shipping glob that collects these files keeps matching them."""
    assert logmod.worker_log_file("/app/logs/web", 123) == "/app/logs/web.123.log"


def test_worker_log_file_empty_is_passthrough(logmod):
    """An empty path stays empty — file logging turned off means off, not a file named after the process id."""
    assert logmod.worker_log_file("", 123) == ""


def test_worker_log_file_rejects_trailing_slash_dir(logmod):
    """A path that names a directory is refused rather than quietly producing a strangely-named file inside it."""
    with pytest.raises(ValueError):
        logmod.worker_log_file("/app/logs/", 123)


def test_worker_log_file_rejects_existing_directory(logmod, tmp_path):
    """An existing directory is refused outright instead of writing a sibling file beside it, which nobody would think to look for."""
    with pytest.raises(ValueError):
        logmod.worker_log_file(str(tmp_path), 123)          # a real directory -> refuse, don't write a sibling


def test_bad_log_path_logs_at_error_level(logmod, isolated_root_logger, caplog, tmp_path):
    """An unusable log path is reported at error level, so file logging can never fail silently and leave someone hunting for records that were never written."""
    # Impossible on EVERY OS: a regular file used as a parent directory — makedirs can't create a
    # subdir under a file. (The old "/dev/null/cannot/web.log" is impossible only on Unix; on Windows
    # makedirs happily creates C:\dev\null\cannot, so no error fired and the test failed there.)
    blocker = tmp_path / "afile"
    blocker.write_text("x")
    bad = os.path.join(str(blocker), "cannot", "web.log")
    with caplog.at_level(logging.ERROR):
        logmod.configure_logging(enable=True, log_file=bad, force=True)
    assert any(r.levelno == logging.ERROR and "file logging disabled" in r.getMessage()
               for r in caplog.records)


def test_access_log_marks_a_truncated_long_path(make_client, fake_users, caplog):
    """A very long path is capped AND the truncation is marked, so a reader can tell a shortened line from a complete one rather than trusting a partial path as the whole request."""
    client = make_client(fake_users)
    with caplog.at_level(logging.INFO):
        client.get("/" + "a" * 300)                         # path longer than the 200-char cap
    line = next((r.getMessage() for r in caplog.records if "aaaa" in r.getMessage()), "")
    assert line, "expected an access-log line"
    assert "…" in line                                      # truncation is marked, not silent
    assert line.count("a") < 300                            # the path body was actually capped


def test_configuring_twice_without_force_does_not_stack_handlers(logmod, isolated_root_logger):
    """A second call is a no-op, so a module imported twice — or a worker that re-initialises — does not
    end up writing every log line two or three times.

    Measured: deleting the idempotence guard left the whole suite green (1054 passed). Every existing
    test either calls configure_logging once or passes force=True, so none of them could observe it.

    The assertion is on handler IDENTITY, not on the count. Without the guard the call falls through to
    the teardown loop, which closes the existing managed handlers and builds replacements — so the count
    comes out the same and only the objects differ. A counting assertion passes either way; measured, it
    did not fail the mutation.
    """
    def managed(root):
        return [h for h in root.handlers if getattr(h, logmod._MANAGED, False)]

    root = logmod.configure_logging(enable=True, log_file="")
    before = managed(root)
    assert before, "the first call must install at least one handler"
    logmod.configure_logging(enable=True, log_file="")
    after = managed(root)
    assert [id(h) for h in after] == [id(h) for h in before], \
        "a second call must leave the existing handlers untouched, not tear them down and rebuild"


def test_every_documented_truthy_spelling_switches_logging_on(logmod):
    """All the spellings the deployment docs use mean the same thing, so ENABLE_LOGGING=on behaves
    exactly like ENABLE_LOGGING=1 rather than silently disabling logging in production.

    Measured: dropping "on" from the accepted set left the whole suite green (1054 passed) — a deployment
    written that way would have run with logging off and nobody would have been told.
    """
    for spelling in ("1", "true", "TRUE", "yes", "on", " On "):
        assert logmod._truthy(spelling) is True, f"{spelling!r} must read as enabled"
    for spelling in ("0", "false", "no", "off", ""):
        assert logmod._truthy(spelling) is False, f"{spelling!r} must read as disabled"
