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


def _fake_smtp(seen):
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

        def send_message(self, msg, from_addr=None, to_addrs=None):
            seen.update(to=msg["To"], subject=msg["Subject"], from_header=str(msg["From"]),
                        envelope_from=from_addr, to_addrs=to_addrs,
                        date=msg["Date"], message_id=msg["Message-ID"], reply_to=msg["Reply-To"])

    return FakeSMTP


def test_smtp_backend_uses_the_configured_relay(monkeypatch):
    seen = {}
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _fake_smtp(seen))
    ok = email_mod.send_email(
        {"SMTP_HOST": "relay.test", "SMTP_PORT": 2525, "SMTP_USER": "u", "SMTP_PASS": "p",
         "SMTP_STARTTLS": True, "MAIL_FROM": "Coach <x@y.co>"},
        "to@z.co", "Reset", "link")
    assert ok is True
    assert seen["host"] == "relay.test" and seen["port"] == 2525
    assert seen["to"] == "to@z.co" and seen.get("tls") and seen["login"] == ("u", "p")
    assert seen["envelope_from"] == "x@y.co" and seen["to_addrs"] == ["to@z.co"]   # explicit clean envelope


def test_smtp_message_carries_date_message_id_and_reply_to(monkeypatch):
    # Strict receivers (Outlook/Microsoft, Proton, institutional mail like Technion) treat a MISSING Date or
    # Message-ID as a spam signal and folder/drop otherwise-legitimate OTP/reset mail. Pin that both are set
    # (Message-ID scoped to the sending domain) plus a Reply-To — the deliverability fix for #270.
    seen = {}
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _fake_smtp(seen))
    ok = email_mod.send_email(
        {"SMTP_HOST": "relay.test", "MAIL_FROM": "Work Smarter <no-reply@worksmarternotharder.dev>"},
        "user@outlook.com", "Your login code", "123456")
    assert ok is True
    assert seen["date"], "a Date header is required by strict receivers"
    assert seen["message_id"] and seen["message_id"].endswith("@worksmarternotharder.dev>"), \
        "Message-ID must be set and scoped to the sending domain"
    assert seen["reply_to"] == "no-reply@worksmarternotharder.dev"


def test_smtp_from_and_envelope_survive_a_comma_display_name(monkeypatch):
    # Regression: MAIL_FROM with a COMMA in the display name (the full "Work Smarter, Not Harder" rename)
    # made smtplib read it as an address list and collapse the envelope sender to a bare name -> SMTP 501,
    # so OTP / reset emails silently never sent. The From header must be quoted and the envelope sender must
    # be the clean address.
    seen = {}
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _fake_smtp(seen))
    ok = email_mod.send_email(
        {"SMTP_HOST": "relay.test", "SMTP_PORT": 587,
         "MAIL_FROM": "Work Smarter, Not Harder <no-reply@worksmarternotharder.dev>"},
        "user@gmail.com", "Your login code", "123456")
    assert ok is True
    assert seen["envelope_from"] == "no-reply@worksmarternotharder.dev"            # clean address, not a name
    assert seen["from_header"] == '"Work Smarter, Not Harder" <no-reply@worksmarternotharder.dev>'  # quoted name


def test_split_sender_bare_valid_and_malformed():
    assert email_mod._split_sender("Coach <x@y.co>") == ("Coach", "x@y.co")
    assert email_mod._split_sender("x@y.co") == ("", "x@y.co")                         # bare address
    assert email_mod._split_sender("Work Smarter, Not Harder <a@b.co>") == ("Work Smarter, Not Harder", "a@b.co")
    assert email_mod._split_sender("Name <>") == ("Name", "")                          # empty <> -> empty addr, keeps the name
    assert email_mod._split_sender("A >x< <a@b.co>") == ("A >x<", "a@b.co")            # address is the LAST <...> pair


def test_malformed_mail_from_falls_back_and_never_emits_a_bare_comma(monkeypatch):
    # A comma display name with NO real address ("<>") must NOT reintroduce the comma bug: the envelope
    # falls back to a clean address, and the From header keeps the (quoted) name — never a bare comma.
    seen = {}
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _fake_smtp(seen))
    ok = email_mod.send_email({"SMTP_HOST": "relay.test", "MAIL_FROM": "Work Smarter, Not Harder <>"},
                              "user@gmail.com", "code", "1")
    assert ok is True
    assert seen["envelope_from"] == email_mod._FALLBACK_ADDR                            # clean fallback (has @)
    assert seen["from_header"] == '"Work Smarter, Not Harder" <%s>' % email_mod._FALLBACK_ADDR


def test_control_chars_in_recipient_abort_the_send(monkeypatch):
    # SMTP-injection guard: a CR/LF in the recipient must abort (return False) before any SMTP command runs.
    sent = {"connected": False}

    class NoSend:
        def __init__(self, *a, **k):
            sent["connected"] = True

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def ehlo(self):
            pass

        def starttls(self, context=None):
            pass

        def login(self, u, p):
            pass

        def send_message(self, *a, **k):
            sent["sent"] = True

    monkeypatch.setattr(email_mod.smtplib, "SMTP", NoSend)
    ok = email_mod.send_email({"SMTP_HOST": "relay.test", "MAIL_FROM": "C <c@x.co>"},
                              "victim@x.co\r\nRCPT TO:<evil@x.co>", "s", "b")
    assert ok is False and sent["connected"] is False   # never even opened the SMTP connection


def test_send_email_async_stays_sync_for_the_log_backend(caplog):
    # No SMTP_HOST (dev / CI / grading): no thread — logs synchronously, so ordering + the dev-surfaced code
    # in the response stay deterministic. The AUTH-H1/H2 oracle only exists on the live SMTP path.
    with caplog.at_level(logging.INFO):
        ok = email_mod.send_email_async({}, "a@b.co", "Your code", "code: 771")
    assert ok is True and "771" in caplog.text


def test_send_email_async_offloads_the_live_send_to_a_thread(monkeypatch):
    # Live SMTP: the send runs in a background thread so the request returns immediately regardless of which
    # (registered vs not) branch it took -> no response-time enumeration (AUTH-H1/H2).
    import threading
    seen, done = {}, threading.Event()
    Fake = _fake_smtp(seen)
    real_send = Fake.send_message
    def _send(self, msg, from_addr=None, to_addrs=None):
        real_send(self, msg, from_addr=from_addr, to_addrs=to_addrs)
        done.set()
    Fake.send_message = _send
    monkeypatch.setattr(email_mod.smtplib, "SMTP", Fake)
    ok = email_mod.send_email_async({"SMTP_HOST": "relay.test", "MAIL_FROM": "C <c@x.co>"}, "to@z.co", "s", "b")
    assert ok is True                                  # returned without blocking on the (backgrounded) send
    assert done.wait(2.0), "the live send must complete on the background thread"
    assert seen["to"] == "to@z.co"
