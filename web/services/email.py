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
import threading
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from html import escape as _escape

logger = logging.getLogger(__name__)

_BRAND = "Work Smarter, Not Harder"


def _email_shell(inner_html):
    """Wrap content in an Outlook-safe email shell: table layout + inline styles ONLY (no <style> block,
    no flexbox/grid — Outlook renders with Word and drops all of it), matching the app's dark identity."""
    return (
        '<!DOCTYPE html><html lang="en"><head>'
        # Tell Outlook / Apple Mail this design is dark ON PURPOSE, so their dark modes don't re-tint the
        # near-black card to a washed-out grey (the "background too light/grey" part of #270).
        '<meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark">'
        '</head><body style="margin:0;padding:0;background:#0b1120;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#0b1120;'
        'padding:26px 12px;font-family:Arial,Helvetica,sans-serif;"><tr><td align="center">'
        '<table role="presentation" width="460" cellpadding="0" cellspacing="0" style="max-width:460px;'
        'width:100%;background:#141c31;border:1px solid #26304a;border-radius:14px;">'
        '<tr><td style="padding:26px 30px 0;">'
        '<div style="color:#7ff0cf;font-size:17px;font-weight:bold;">' + _BRAND + '</div>'
        '<div style="color:#8792a8;font-size:12px;padding-top:2px;">readiness, every morning</div></td></tr>'
        '<tr><td style="padding:16px 30px 28px;">' + inner_html + '</td></tr></table>'
        '<div style="color:#5b6478;font-size:11px;line-height:1.5;padding:16px 8px 0;max-width:460px;">'
        'Work Smarter, Not Harder &middot; worksmarternotharder.dev</div>'
        '</td></tr></table></body></html>'
    )


def code_email_html(code, minutes, intro, why):
    """Branded HTML for a one-time code. The code is shown big + monospace so it's trivially
    select-to-copy (long-press on mobile, double-click on desktop) and recognized by iOS/Android OTP
    autofill. Email clients strip JS, so a real one-click 'copy' button is impossible — this is the
    universal equivalent. `intro`/`why` are plain text (escaped)."""
    safe_code = _escape("".join(ch for ch in str(code) if ch.isalnum()))
    inner = (
        '<div style="color:#c7d0e0;font-size:15px;line-height:1.55;">' + _escape(intro) + '</div>'
        # Mint border so the code POPS against the dark card (matches the reset email's mint button); white
        # digits on the near-black fill stay maximally legible even if a client re-tints the surrounding card.
        '<div style="text-align:center;padding:22px 0 8px;"><span style="display:inline-block;'
        'background:#0b1120;border:2px solid #7ff0cf;border-radius:12px;padding:16px 26px;'
        'font-family:\'Courier New\',Courier,monospace;font-size:34px;line-height:1;letter-spacing:9px;'
        'color:#ffffff;font-weight:bold;">' + safe_code + '</span></div>'
        '<div style="color:#8792a8;font-size:12.5px;line-height:1.5;padding-bottom:16px;">'
        'Tap and hold (phone) or double-click (computer) the code to copy it — on most phones your '
        'keyboard will offer to fill it in for you. It expires in ' + str(int(minutes)) + ' minutes.</div>'
        '<div style="border-top:1px solid #26304a;padding-top:14px;color:#6b7488;font-size:12px;'
        'line-height:1.5;">' + _escape(why) + '</div>'
    )
    return _email_shell(inner)


def link_email_html(intro, link, button_label, why):
    """Branded HTML with a single action button (e.g. password reset). Uses an <a> styled as a button —
    Outlook-safe (no JS). `link` is our own signed-token URL; `intro`/`why`/`button_label` are text."""
    safe_link = _escape(link, quote=True)
    inner = (
        '<div style="color:#c7d0e0;font-size:15px;line-height:1.55;">' + _escape(intro) + '</div>'
        '<div style="text-align:center;padding:22px 0 10px;"><a href="' + safe_link + '" '
        'style="display:inline-block;background:#7ff0cf;color:#0b1120;text-decoration:none;font-weight:bold;'
        'font-size:15px;padding:13px 26px;border-radius:10px;">' + _escape(button_label) + '</a></div>'
        '<div style="color:#8792a8;font-size:12px;line-height:1.5;padding-bottom:16px;word-break:break-all;">'
        'Or paste this link into your browser:<br>' + _escape(link) + '</div>'
        '<div style="border-top:1px solid #26304a;padding-top:14px;color:#6b7488;font-size:12px;'
        'line-height:1.5;">' + _escape(why) + '</div>'
    )
    return _email_shell(inner)


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


def send_email(config, to, subject, body, html=None, force_mock=False):
    """Send `body` to `to`. SMTP when ``SMTP_HOST`` is configured, else the log backend. Returns
    True if handed off (or logged), False if a configured SMTP send failed — never raises.

    ``html`` (optional) adds a rich HTML alternative to the plaintext ``body`` (multipart/alternative):
    clients that render HTML show it, everything else falls back to ``body`` — so a client that strips
    HTML, or a broken template, still delivers the code/link. The plaintext ``body`` stays authoritative.

    ``force_mock`` (the gated dev email-mock override) forces the log backend even where SMTP is
    configured: nothing is sent, the message (incl. the code) is only logged. The caller then returns
    the code in its response. Off by default; the auth layer sets it only behind ``AUTH_DEBUG_EMAIL``."""
    host = None if force_mock else config.get("SMTP_HOST")
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
        # Date + Message-ID are expected by strict receivers (Outlook/Microsoft, Proton, institutional mail
        # like Technion); their ABSENCE is a spam signal that folders or silently drops otherwise-legitimate
        # OTP/reset mail. Set them explicitly (smtplib doesn't). Reply-To points replies at the sender.
        msg["Date"] = formatdate(localtime=True)
        msg["Message-ID"] = make_msgid(domain=addr.rsplit("@", 1)[-1] if "@" in addr else None)
        msg["Reply-To"] = addr
        msg.set_content(body)                    # plaintext part (authoritative fallback)
        if html:
            msg.add_alternative(html, subtype="html")   # richer HTML part; clients pick the best they render
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


def send_email_async(config, to, subject, body, html=None, force_mock=False):
    """Fire-and-forget send for the account-enumeration-sensitive paths (forgot-password, register).

    Closes the AUTH-H1/H2 response-time side channel: a synchronous SMTP send makes the branch that emails
    a *registered* address measurably slower than the branch that emails nothing (or does less), so an
    attacker can distinguish "registered" from "not" even though the response BODY is identical. Running the
    live send in a daemon thread makes the request return immediately regardless of which branch it took.

    The log backend (no ``SMTP_HOST`` / ``force_mock`` — dev / CI / grading) stays SYNCHRONOUS: it's a fast
    ``logger.info`` with no oracle, and dev/tests read the code from the response body, so nothing about
    ordering or determinism changes there. Only the slow live-SMTP path is offloaded. Never raises
    (``send_email`` swallows every error); the code/link is valid server-side whether or not delivery lands."""
    host = None if force_mock else config.get("SMTP_HOST")
    if not host:                                   # log backend: fast + no oracle -> keep it sync (tests/dev rely on this)
        return send_email(config, to, subject, body, html=html, force_mock=force_mock)
    snapshot = dict(config)                        # decouple from the request thread's app/config context
    threading.Thread(target=send_email, args=(snapshot, to, subject, body),
                     kwargs={"html": html, "force_mock": force_mock}, daemon=True, name="email-send").start()
    return True
