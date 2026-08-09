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
    """With no relay configured the code is written to the log and nothing leaves the machine — the development path a teammate can run without a mail account."""
    with caplog.at_level(logging.INFO):
        ok = email_mod.send_email({}, "athlete@example.com", "Your code", "code: 482913")
    assert ok is True
    assert "482913" in caplog.text                 # dev backend logs it; nothing leaves the box


def test_smtp_failure_returns_false_and_never_raises(monkeypatch):
    """A mail server that is down must not 500 a login or a password reset: the failure is reported and swallowed, so the user still gets an answer."""
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
                        envelope_from=from_addr, to_addrs=to_addrs, msg=msg,
                        date=msg["Date"], message_id=msg["Message-ID"], reply_to=msg["Reply-To"])

    return FakeSMTP


def test_smtp_backend_uses_the_configured_relay(monkeypatch):
    """Mail genuinely goes to the configured relay, over TLS, authenticated — with an explicit clean envelope sender rather than whatever the library would infer."""
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
    """Strict receivers treat a missing Date or Message-ID as a spam signal and folder or drop otherwise-legitimate login and reset mail.

    Both are set — the Message-ID scoped to the sending domain — alongside a Reply-To.
    """
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
    """A comma in the display name made the mail library read it as an address LIST and collapse the envelope sender to a bare name, which the relay rejected — so login and reset emails silently never sent.

    The From header must be quoted and the envelope sender must be the clean address.
    """
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
    """The sender parser handles every shape the configuration can hold: a named address, a bare address, a name containing a comma, an empty pair of brackets, and stray angle brackets inside the name."""
    assert email_mod._split_sender("Coach <x@y.co>") == ("Coach", "x@y.co")
    assert email_mod._split_sender("x@y.co") == ("", "x@y.co")                         # bare address
    assert email_mod._split_sender("Work Smarter, Not Harder <a@b.co>") == ("Work Smarter, Not Harder", "a@b.co")
    assert email_mod._split_sender("Name <>") == ("Name", "")                          # empty <> -> empty addr, keeps the name
    assert email_mod._split_sender("A >x< <a@b.co>") == ("A >x<", "a@b.co")            # address is the LAST <...> pair


def test_malformed_mail_from_falls_back_and_never_emits_a_bare_comma(monkeypatch):
    """A comma display name with no real address must not reintroduce the comma bug: the envelope falls back to a clean address while the header keeps the quoted name — never a bare comma."""
    seen = {}
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _fake_smtp(seen))
    ok = email_mod.send_email({"SMTP_HOST": "relay.test", "MAIL_FROM": "Work Smarter, Not Harder <>"},
                              "user@gmail.com", "code", "1")
    assert ok is True
    assert seen["envelope_from"] == email_mod._FALLBACK_ADDR                            # clean fallback (has @)
    assert seen["from_header"] == '"Work Smarter, Not Harder" <%s>' % email_mod._FALLBACK_ADDR


def test_control_chars_in_recipient_abort_the_send(monkeypatch):
    """A newline in the recipient is an attempt to append extra SMTP commands, so the send aborts before the connection is so much as opened."""
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


def test_html_alternative_is_attached_with_plaintext_fallback(monkeypatch):
    """With an HTML body the message is multipart/alternative: rich clients render the styled version and everything else falls back to plaintext, so the code arrives either way.

    Both parts carry it, and the deliverability headers stay on the multipart root.
    """
    seen = {}
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _fake_smtp(seen))
    html = email_mod.code_email_html("246813", 10, "Here's your login code:", "why you got this")
    ok = email_mod.send_email(
        {"SMTP_HOST": "relay.test", "MAIL_FROM": "Work Smarter <no-reply@worksmarternotharder.dev>"},
        "user@outlook.com", "Your login code", "Your login code is: 246813", html=html)
    assert ok is True
    msg = seen["msg"]
    assert msg.get_content_type() == "multipart/alternative"
    plain = msg.get_body(preferencelist=("plain",))
    rich = msg.get_body(preferencelist=("html",))
    assert plain is not None and "246813" in plain.get_content()     # plaintext fallback keeps the code
    assert rich is not None and "246813" in rich.get_content()       # HTML part shows the code too
    assert msg["Date"] and msg["Message-ID"] and msg["Reply-To"]     # headers survive on the root


def test_no_html_stays_single_part_plaintext(monkeypatch):
    """Without an HTML body the message stays a single plaintext part, so a caller that passes no template is untouched by the multipart support."""
    seen = {}
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _fake_smtp(seen))
    ok = email_mod.send_email(
        {"SMTP_HOST": "relay.test", "MAIL_FROM": "W <no-reply@worksmarternotharder.dev>"},
        "u@z.co", "s", "plain body only")
    assert ok is True
    assert seen["msg"].get_content_type() == "text/plain"


def test_code_email_html_shows_the_code_and_select_to_copy_hint():
    """The code email renders the code, tells the reader to select it to copy it (email cannot run JavaScript), states how long it lasts, and explains why they received it."""
    html = email_mod.code_email_html("135790", 7, "Here's your code:", "a reason line")
    assert "135790" in html                                          # the code is rendered
    assert "copy" in html.lower()                                    # select-to-copy guidance (email has no JS)
    assert "expires in 7 minutes" in html
    assert "a reason line" in html                                   # the why-you-got-this footer


def test_link_email_html_has_a_button_and_the_raw_link():
    """The link email carries a real anchor button AND the raw URL, so a client that blocks buttons still leaves the reader a way through."""
    link = "https://app.worksmarternotharder.dev/?reset_token=abc.def"
    html = email_mod.link_email_html("Reset it:", link, "Reset your password", "a reason")
    assert 'href="' + link in html and "Reset your password" in html  # a real <a> button (Outlook-safe, no JS)
    assert link in html                                               # raw link too, for clients that block buttons


def test_send_email_async_stays_sync_for_the_log_backend(caplog):
    """With no relay configured there is no background thread, so log ordering and the development-surfaced code stay deterministic."""
    with caplog.at_level(logging.INFO):
        ok = email_mod.send_email_async({}, "a@b.co", "Your code", "code: 771")
    assert ok is True and "771" in caplog.text


def test_send_email_async_offloads_the_live_send_to_a_thread(monkeypatch):
    """On the live path the send is backgrounded so the request returns at the same speed whether or not the address belongs to a registered user — otherwise the response time itself reveals which emails have accounts."""
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


# ---- gaps found by mutating web/services/email.py against the whole suite (#434) ----
def test_starttls_is_on_by_default_when_the_relay_config_does_not_mention_it(monkeypatch):
    """A relay configured without an explicit TLS setting is still contacted over TLS, so a deployment
    that simply does not set SMTP_STARTTLS never ships one-time codes and reset links in cleartext.

    The sibling relay test passes `SMTP_STARTTLS: True` itself, so it asserts the value it just set and
    can never see the DEFAULT change. Measured: flipping the default to False left the whole suite green
    (1054 passed) — every OTP and reset link would have crossed the network unencrypted.
    """
    seen = {}
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _fake_smtp(seen))
    ok = email_mod.send_email({"SMTP_HOST": "relay.test", "MAIL_FROM": "C <x@y.co>"},   # no SMTP_STARTTLS key
                              "to@z.co", "Your code", "482913")
    assert ok is True
    assert seen.get("tls") is True, "TLS must be the default, not something a deployment has to remember"


def test_the_debug_mock_never_reaches_the_relay(monkeypatch):
    """The gated dev override logs the message instead of sending it, EVEN where a live relay is
    configured — otherwise turning the debug tool on would mail real people from a real account.

    Measured: ignoring `force_mock` left the whole suite green (1054 passed). Every existing mock-backend
    test runs with no SMTP_HOST at all, where the log backend is taken anyway — so none of them could
    tell whether the override does anything.
    """
    seen = {}
    monkeypatch.setattr(email_mod.smtplib, "SMTP", _fake_smtp(seen))
    ok = email_mod.send_email({"SMTP_HOST": "relay.test", "MAIL_FROM": "C <x@y.co>"},
                              "to@z.co", "Your code", "482913", force_mock=True)
    assert ok is True
    assert seen == {}, f"force_mock must not open a connection to the relay, but reached it: {seen}"


def test_a_live_send_does_not_block_the_caller(monkeypatch):
    """A live send runs off the request thread, so the response time of a forgot-password request does
    not reveal whether the address was registered.

    That is the whole reason send_email_async exists. Measured: making it synchronous for the live-SMTP
    path left the whole suite green (1054 passed) — the timing side channel would have been back, and
    the existing async tests all run the log backend, which is synchronous BY DESIGN.
    """
    import threading
    ran_on = {}
    done = threading.Event()

    def record(*a, **k):
        ran_on["thread"] = threading.current_thread().name
        done.set()
        return True

    monkeypatch.setattr(email_mod, "send_email", record)
    assert email_mod.send_email_async({"SMTP_HOST": "relay.test"}, "to@z.co", "s", "b") is True
    assert done.wait(5), "the queued send never ran"
    assert ran_on["thread"] != threading.current_thread().name, "a live send must not run on the caller's thread"


def test_a_sender_with_no_usable_bracket_pair_is_treated_as_a_bare_address(monkeypatch):
    """A malformed sender with its brackets the wrong way round yields NO display name, so a fragment of
    the raw configuration string can never end up presented as the sender's name.

    The address half is already covered (it falls back to a safe one). The NAME half was not: measured,
    dropping the `lt < gt` ordering check left the whole suite green (1054 passed), and under it this
    input produces the name "a> b" out of what is simply a broken config value.
    """
    assert email_mod._split_sender("a> b <c") == ("", "a> b <c")
    assert email_mod._split_sender("Coach <x@y.co>") == ("Coach", "x@y.co")   # the well-formed case still works
