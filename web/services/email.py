"""Email delivery for OTP + password-reset. OWNER: Lior.

Backend-agnostic by design:
  * **log backend (default)** — no ``SMTP_HOST`` set: the message (incl. the code / reset link) is written
    to the app log. Zero credentials, nothing leaves the box — perfect for dev / demo / grading.
  * **SMTP backend** — set ``SMTP_HOST`` (+ ``SMTP_USER`` / ``SMTP_PASS``) in the environment to send real
    mail over STARTTLS (e.g. a free Brevo / Gmail-app-password / SendGrid relay).

No credentials live in code — they come from ``.env`` only. Delivery failures never propagate to the
caller: a down mail server must not 500 a login or a reset request, so it's logged and the flow continues
(the code / link is still valid server-side).
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

logger = logging.getLogger(__name__)


_FALLBACK_ADDR = "no-reply@worksmarter.local"   # used only if MAIL_FROM has no usable address (broken config)


def _split_sender(raw):
    """Split ``"Display Name <addr>"`` (or a bare ``addr``) into ``(name, addr)``. ``addr`` may be "".

    Done by hand rather than ``email.utils.parseaddr`` because a display name containing a COMMA (e.g.
    "Work Smarter, Not Harder") reads as an address-LIST separator: parseaddr returns ``('', '')`` and the
    envelope sender collapses to a bare name — which is exactly what got the SMTP send rejected (501
    "expecting MAIL arg syntax of FROM:<address>"). Extracting the ``<addr>`` span is comma-safe. The
    ``lt < gt`` guard means an empty/backwards ``<>`` yields ``addr == ""`` (a missing address) rather than
    silently swallowing the name — the caller substitutes a fallback address, never the raw comma string.
    """
    raw = (raw or "").strip()
    lt, gt = raw.rfind("<"), raw.rfind(">")             # the address lives in the LAST <...> pair
    if 0 <= lt < gt:
        return raw[:lt].strip().strip('"'), raw[lt + 1 : gt].strip()   # (name, addr); addr may be ""
    return "", raw                                                     # bare address (no brackets)


def send_email(config, to, subject, body):
    """Send `body` to `to`. SMTP when ``SMTP_HOST`` is configured, else the log backend. Returns
    True if handed off (or logged), False if a configured SMTP send failed — never raises."""
    host = config.get("SMTP_HOST")
    sender = config.get("MAIL_FROM") or "Work Smarter, Not Harder <no-reply@worksmarter.local>"
    if not host:
        logger.info("EMAIL (log backend) to=%s subject=%r\n%s", to, subject, body)
        return True
    try:
        name, addr = _split_sender(sender)
        if "@" not in addr:                      # missing/malformed address -> a safe fallback, NEVER the raw
            name, addr = name, _FALLBACK_ADDR    # comma string (which would re-break the header + envelope)
        # Defence in depth on the OTP/reset hot path: the header setters below already reject CR/LF (the
        # EmailMessage default policy), but the envelope args go straight to smtplib's RCPT/MAIL commands, so
        # refuse control chars in the sender + recipient explicitly before anything reaches the wire.
        if any(c in "\r\n" for c in addr + str(to)):
            raise ValueError("control characters in an email address")
        msg = EmailMessage()
        msg["From"] = formataddr((name, addr))   # name is quoted if it has a comma/special char; addr stays clean
        msg["To"], msg["Subject"] = to, subject
        msg.set_content(body)
        with smtplib.SMTP(host, int(config.get("SMTP_PORT") or 587), timeout=10) as server:
            server.ehlo()
            if config.get("SMTP_STARTTLS", True):
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if config.get("SMTP_USER"):
                server.login(config["SMTP_USER"], config.get("SMTP_PASS") or "")
            # Pass the clean address as the ENVELOPE sender explicitly, so a display name (with a comma or
            # other special char) can never corrupt what smtplib would otherwise derive from the header.
            server.send_message(msg, from_addr=addr, to_addrs=[to])
        logger.info("EMAIL (smtp) sent to=%s subject=%r", to, subject)
        return True
    except Exception:
        logger.exception("EMAIL send failed to=%s (flow continues; code/link still valid server-side)", to)
        return False
