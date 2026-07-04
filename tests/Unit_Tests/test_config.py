"""Unit tests for env-driven config parsing. OWNER: Lior.

A typo'd integer env var must NOT crash the app at import — it falls back to the default so a worker
still boots (a bad MAX_CONTENT_LENGTH should degrade to the safe default, not kill gunicorn on import).
Also pins the course-mandated `debug` flag: FLASK_DEBUG must toggle Flask's debug mode.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"


@pytest.fixture
def cfg(web_app_module):
    # web/app.py imported `config` while loading -> it's cached in sys.modules.
    return sys.modules["config"]


def _reload_config():
    """Re-exec config.py so the import-time env reads (DEBUG/TESTING) are evaluated fresh."""
    spec = importlib.util.spec_from_file_location("config_probe", str(WEB / "config.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_int_env_missing_uses_default(cfg):
    assert cfg._int_env("WS_DEFINITELY_UNSET_VAR", 4242) == 4242


def test_int_env_garbage_falls_back(cfg, monkeypatch):
    monkeypatch.setenv("WS_TEST_INT", "64kb")  # a realistic typo
    assert cfg._int_env("WS_TEST_INT", 4242) == 4242


def test_int_env_valid_value_is_used(cfg, monkeypatch):
    monkeypatch.setenv("WS_TEST_INT", "100")
    assert cfg._int_env("WS_TEST_INT", 4242) == 100


def test_int_env_non_positive_falls_back(cfg, monkeypatch):
    monkeypatch.setenv("WS_TEST_INT", "-5")  # a body cap <= 0 is nonsensical -> safe default
    assert cfg._int_env("WS_TEST_INT", 4242) == 4242


# ---- the course-mandated `debug` flag (TA notes: "a debug flag that enables debug mode") ----
def test_flask_debug_flag_on(monkeypatch):
    monkeypatch.setenv("FLASK_DEBUG", "1")
    assert _reload_config().Config.DEBUG is True


def test_flask_debug_flag_off_by_default(monkeypatch):
    monkeypatch.delenv("FLASK_DEBUG", raising=False)
    assert _reload_config().Config.DEBUG is False


def test_flask_debug_flag_off_when_zero(monkeypatch):
    monkeypatch.setenv("FLASK_DEBUG", "0")
    assert _reload_config().Config.DEBUG is False


def test_create_app_honours_the_debug_flag(monkeypatch, web_app_module):
    # end-to-end: FLASK_DEBUG -> Config.DEBUG -> app.config["DEBUG"] (Flask's debug mode)
    monkeypatch.setenv("FLASK_DEBUG", "1")
    app = web_app_module.create_app(config=_reload_config().Config)
    app.config.update(SECRET_KEY="test-secret-key")
    assert app.config["DEBUG"] is True


# ---- config <-> docker-compose passthrough (a knob config.py reads MUST be forwarded to the container) ----
def test_compose_forwards_every_auth_email_knob():
    """docker-compose.yml promises "teammates flip any mode in .env ALONE (no compose edit)". A knob that
    config.py reads from the environment but the web service does NOT pass through silently ignores the .env
    value and falls back to the code default (the RESET_TOKEN_MAX_AGE gap). Guard the whole class here so a
    newly-added auth/email knob can't be forgotten in compose.
    """
    compose = (WEB.parent / "docker-compose.yml").read_text()
    knobs = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "SMTP_STARTTLS", "MAIL_FROM",
             "APP_BASE_URL", "RESET_TOKEN_MAX_AGE", "OTP_ENABLED", "OTP_TTL_SECONDS",
             "OTP_MAX_ATTEMPTS", "REGISTER_VERIFY_EMAIL", "REMEMBER_COOKIE_MAX_AGE")
    missing = [k for k in knobs if "${" + k not in compose]
    assert not missing, f"config.py reads these but docker-compose.yml doesn't pass them through: {missing}"
