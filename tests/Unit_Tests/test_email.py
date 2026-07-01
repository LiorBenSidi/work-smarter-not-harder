"""Unit tests for the email service (log + SMTP backends). OWNER: Lior.

web/ isn't an installed package, so email.py is exec'd off disk. Contract: the log backend never touches
the network (it just logs); the SMTP backend sends via the configured relay and must SWALLOW failures —
a down mail server must not 500 a login or a reset request.
"""
import importlib.util
import logging
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"


def _load():
    spec = importlib.util.spec_from_file_location("ws_email_under_test", str(WEB / "services" / "email.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


email_mod = _load()


def test_log_backend_returns_true_and_surfaces_the_body(caplog):
    with caplog.at_level(logging.INFO):
        ok = email_mod.send_email({}, "athlete@example.com", "Your code", "code: 482913")
    assert ok is True
    assert "482913" in caplog.text                 # dev backend logs it; nothing leaves the box


def test_smtp_failure_returns_false_and_never_raises(monkeypatch):
    def boom(*a, **k):
        raise OSError("relay unreachable")
    monkeypatch.setattr(email_mod.smtplib, "SMTP", boom)
    assert email_mod.send_email({"SMTP_HOST": "smtp.example.com"}, "a@b.co", "s", "b") is False


def test_smtp_backend_uses_the_configured_relay(monkeypatch):
    seen = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            seen.update(host=host, port=port)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self, context=None):
            seen["tls"] = True

        def login(self, user, pw):
            seen["login"] = (user, pw)

        def send_message(self, msg):
            seen.update(to=msg["To"], subject=msg["Subject"])

    monkeypatch.setattr(email_mod.smtplib, "SMTP", FakeSMTP)
    ok = email_mod.send_email(
        {"SMTP_HOST": "relay.test", "SMTP_PORT": 2525, "SMTP_USER": "u", "SMTP_PASS": "p",
         "SMTP_STARTTLS": True, "MAIL_FROM": "Coach <x@y.co>"},
        "to@z.co", "Reset", "link")
    assert ok is True
    assert seen["host"] == "relay.test" and seen["port"] == 2525
    assert seen["to"] == "to@z.co" and seen.get("tls") and seen["login"] == ("u", "p")
