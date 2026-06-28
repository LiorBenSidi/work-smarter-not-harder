"""Unit tests for env-driven config parsing. OWNER: Lior.

A typo'd integer env var must NOT crash the app at import — it falls back to the default so a worker
still boots (a bad MAX_CONTENT_LENGTH should degrade to the safe default, not kill gunicorn on import).
"""
import sys

import pytest


@pytest.fixture
def cfg(web_app_module):
    # web/app.py imported `config` while loading -> it's cached in sys.modules.
    return sys.modules["config"]


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
