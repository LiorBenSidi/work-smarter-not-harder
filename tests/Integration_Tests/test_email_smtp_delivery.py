"""Integration test: the SMTP backend actually TRANSMITS the message over a socket. OWNER: Lior.

test_email.py mocks ``smtplib.SMTP`` (proves we call it right). This complements it by standing up a tiny
in-process SMTP **sink** on localhost and driving the REAL ``smtplib`` client through a full EHLO → MAIL →
RCPT → DATA exchange — so the actual bytes (headers + the OTP/reset body) are proven to leave the app
correctly, without any mock and without a real provider. It's the local proof behind "the actual OTP":
the same code path Brevo will carry, exercised end to end.
"""
import importlib.util
import socketserver
import threading
from pathlib import Path

WEB = Path(__file__).resolve().parents[2] / "web"


def _load_email():
    spec = importlib.util.spec_from_file_location("ws_email_delivery_under_test", str(WEB / "services" / "email.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


email_mod = _load_email()


class _SMTPSinkHandler(socketserver.StreamRequestHandler):
    """Minimal SMTP responder: accepts one message and appends its raw DATA to ``server.messages``."""

    wbufsize = 0  # flush each reply immediately so the smtplib client isn't left waiting

    def handle(self):
        self.wfile.write(b"220 sink ready\r\n")
        in_data, buf = False, []
        while True:
            line = self.rfile.readline()
            if not line:
                break
            if in_data:
                if line.rstrip(b"\r\n") == b".":            # end of DATA
                    in_data = False
                    self.server.messages.append(b"".join(buf))
                    buf = []
                    self.wfile.write(b"250 queued\r\n")
                else:
                    buf.append(line)
                continue
            verb = line.decode("latin1").strip().upper()
            if verb.startswith(("EHLO", "HELO")):
                self.wfile.write(b"250 sink\r\n")            # single-line 250 => no ESMTP extensions
            elif verb.startswith("DATA"):
                self.wfile.write(b"354 go ahead\r\n")
                in_data = True
            elif verb.startswith("QUIT"):
                self.wfile.write(b"221 bye\r\n")
                break
            else:                                            # MAIL / RCPT / RSET / NOOP ...
                self.wfile.write(b"250 ok\r\n")


class _SMTPSinkServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def test_smtp_backend_transmits_the_message_over_a_socket():
    server = _SMTPSinkServer(("127.0.0.1", 0), _SMTPSinkHandler)
    server.messages = []
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        cfg = {"SMTP_HOST": "127.0.0.1", "SMTP_PORT": port, "SMTP_STARTTLS": False, "SMTP_USER": "",
               "MAIL_FROM": "Work Smarter, Not Harder <no-reply@worksmarter.local>"}
        ok = email_mod.send_email(cfg, "grader@example.com", "Your Work Smarter, Not Harder login code",
                                  "Your Work Smarter, Not Harder login code is: 123456\n")
        assert ok is True
        assert server.messages, "the SMTP sink received no message"
        raw = server.messages[0].decode("latin1")
        assert "Subject: Your Work Smarter, Not Harder login code" in raw   # headers transmitted
        assert "To: grader@example.com" in raw
        assert "123456" in raw                                   # the OTP body actually went over the wire
    finally:
        server.shutdown()
        server.server_close()


def test_smtp_backend_returns_false_when_the_relay_refuses(monkeypatch):
    # a relay that refuses the connection (e.g. a bad host / blocked port) must be swallowed, not raised,
    # so a down mail server can't 500 a login or a reset — the code/link stays valid server-side.
    def refusing_handle(self):
        self.wfile.write(b"554 no service here\r\n")   # non-220 greeting -> smtplib SMTPConnectError
    monkeypatch.setattr(_SMTPSinkHandler, "handle", refusing_handle)
    server = _SMTPSinkServer(("127.0.0.1", 0), _SMTPSinkHandler)
    server.messages = []
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        cfg = {"SMTP_HOST": "127.0.0.1", "SMTP_PORT": port, "SMTP_STARTTLS": False, "MAIL_FROM": "x@y.co"}
        assert email_mod.send_email(cfg, "to@z.co", "s", "b") is False   # never raises -> login/reset survive
    finally:
        server.shutdown()
        server.server_close()
