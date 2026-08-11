"""Unit tests for env-driven config parsing. OWNER: Lior.

A typo'd integer env var must NOT crash the app at import — it falls back to the default so a worker
still boots (a bad MAX_CONTENT_LENGTH should degrade to the safe default, not kill gunicorn on import).
Also pins the `debug` flag: FLASK_DEBUG must toggle Flask's debug mode.
"""
import importlib.util
import re
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


@pytest.mark.parametrize("raw,expected", [
    (None,   4242),   # unset            -> the default
    ("64kb", 4242),   # a realistic typo -> the default, never a crash
    ("100",   100),   # a valid value    -> parsed and used
    ("-5",   4242),   # a body cap <= 0 is nonsensical -> the default
])
def test_int_env_parses_a_value_or_falls_back_to_the_default(cfg, monkeypatch, raw, expected):
    """_int_env returns the parsed value only when it is a usable positive int, else the default."""
    if raw is None:
        monkeypatch.delenv("WS_TEST_INT", raising=False)
    else:
        monkeypatch.setenv("WS_TEST_INT", raw)
    assert cfg._int_env("WS_TEST_INT", 4242) == expected


# ---- web->ai timeout invariant: web must wait at least as long as the ai queue computes ----
# The ai queue's own timeout defaults to AI_PREDICT_TIMEOUT_SECONDS=30 (ai/app.py). If web's client
# timeout drops below that, web abandons — and discards — a result ai is still computing, while the
# worker stays busy. Lock the floor so a future "let's shorten the web timeout" can't silently regress it.
_AI_QUEUE_TIMEOUT_DEFAULT = 30


def test_ai_client_timeout_default_is_not_below_the_ai_queue_timeout(cfg):
    """Web must wait at least as long as the AI queue is allowed to compute.

    If its client timeout drops below the queue's, web abandons and discards a result the worker is still busy producing — the user sees a failure for work that succeeded.
    """
    assert cfg.Config.AI_CLIENT_TIMEOUT >= _AI_QUEUE_TIMEOUT_DEFAULT


def test_ai_client_timeout_is_env_tunable(monkeypatch):
    """The timeout is genuinely tunable from the environment, so a slow deploy can be given more room without rebuilding the image."""
    monkeypatch.setenv("AI_CLIENT_TIMEOUT_SECONDS", "45")
    assert _reload_config().Config.AI_CLIENT_TIMEOUT == 45


# The web gunicorn worker timeout must EXCEED AI_CLIENT_TIMEOUT — otherwise gunicorn SIGKILLs the worker
# mid-/predict before ai_client's graceful degrade (return None, DESIGN §5) can fire. Guard both places the
# web command is defined so raising AI_CLIENT_TIMEOUT past the gunicorn timeout can't silently break it.
_REPO = Path(__file__).resolve().parents[2]


def _web_gunicorn_timeout(text):
    """The --timeout value on the gunicorn command that serves web (wsgi:app), or None."""
    text = text.replace("\\\n", " ")  # join Dockerfile CMD line-continuations into one logical line
    for line in text.splitlines():
        if "gunicorn" in line and "wsgi:app" in line:
            m = re.search(r"--timeout['\",\s]+(\d+)", line)
            return int(m.group(1)) if m else None
    return None


@pytest.mark.parametrize("rel", ["web/Dockerfile", "docker-compose.prod.yml"])
def test_web_gunicorn_timeout_exceeds_ai_client_timeout(cfg, rel):
    """The worker timeout must EXCEED the AI client timeout, in both places the web command is defined.

    Otherwise gunicorn kills the worker mid-request before the graceful degrade can fire, turning a handled slow response into a dropped connection.
    """
    t = _web_gunicorn_timeout((_REPO / rel).read_text())
    assert t is not None, f"{rel}: web gunicorn command has no --timeout"
    assert t > cfg.Config.AI_CLIENT_TIMEOUT, f"{rel}: gunicorn --timeout {t} must exceed AI_CLIENT_TIMEOUT"


# ---- the `debug` flag: an explicit switch into debug mode ----
@pytest.mark.parametrize("raw,expected", [
    ("1",  True),    # explicitly on
    (None, False),   # unset -> off, so debug can never be on by accident
    ("0",  False),   # explicitly off
])
def test_flask_debug_flag_is_on_only_when_explicitly_set(monkeypatch, raw, expected):
    """FLASK_DEBUG turns Config.DEBUG on only for "1"; anything else, including unset, leaves it off."""
    if raw is None:
        monkeypatch.delenv("FLASK_DEBUG", raising=False)
    else:
        monkeypatch.setenv("FLASK_DEBUG", raw)
    assert _reload_config().Config.DEBUG is expected


def test_create_app_honours_the_debug_flag(monkeypatch, web_app_module):
    """The environment variable reaches Flask's actual debug mode end to end, so the switch that exposes the interactive debugger is proven to be the one being read — not merely a value stored in a config object nothing consults."""
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


# The three below are the DEFAULTS, not the values any given test runs with. Every functional test of
# the OTP flow builds its client with `make_otp_client(..., OTP_TTL_SECONDS=600, OTP_MAX_ATTEMPTS=5)` —
# it sets the number it then relies on, so it can never notice the default changing underneath it. That
# is why each of these mutations left the whole suite green (measured), and it is the same
# shape as the SMTP_STARTTLS default that shipped one-time codes in cleartext.
@pytest.mark.parametrize("name,expected,why", [
    ("OTP_TTL_SECONDS", 600,
     "a login code valid for a day instead of ten minutes is an intercepted code that still works tomorrow"),
    ("OTP_MAX_ATTEMPTS", 5,
     "a six-digit code with no practical attempt cap is a code that can simply be guessed"),
    ("REMEMBER_COOKIE_MAX_AGE", 30 * 24 * 3600,
     "a trusted-browser cookie that effectively never expires keeps skipping verification forever"),
])
def test_the_security_relevant_defaults_are_the_documented_ones(cfg, name, expected, why):
    """Each of these is the value the app ships with when the deployment says nothing — and each is the
    only thing standing between a configured environment and a much weaker one.

    Pinning a constant is usually a weak test. It earns its place here for the same reason
    test_reset_token_window_is_ten_minutes does: nothing else reads the DEFAULT. Its sibling
    RESET_TOKEN_MAX_AGE is documented as "matches the OTP window" and IS pinned; the OTP window itself
    was not — the same rule enforced in two places with an alarm on only one.
    """
    assert getattr(cfg.Config, name) == expected, why
