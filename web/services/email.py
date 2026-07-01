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

logger = logging.getLogger(__name__)


def send_email(config, to, subject, body):
    """Send `body` to `to`. SMTP when ``SMTP_HOST`` is configured, else the log backend. Returns
    True if handed off (or logged), False if a configured SMTP send failed — never raises."""
    host = config.get("SMTP_HOST")
    sender = config.get("MAIL_FROM") or "Work Smarter <no-reply@worksmarter.local>"
    if not host:
        logger.info("EMAIL (log backend) to=%s subject=%r\n%s", to, subject, body)
        return True
    try:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = sender, to, subject
        msg.set_content(body)
        with smtplib.SMTP(host, int(config.get("SMTP_PORT") or 587), timeout=10) as server:
            server.ehlo()
            if config.get("SMTP_STARTTLS", True):
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
            if config.get("SMTP_USER"):
                server.login(config["SMTP_USER"], config.get("SMTP_PASS") or "")
            server.send_message(msg)
        logger.info("EMAIL (smtp) sent to=%s subject=%r", to, subject)
        return True
    except Exception:
        logger.exception("EMAIL send failed to=%s (flow continues; code/link still valid server-side)", to)
        return False
