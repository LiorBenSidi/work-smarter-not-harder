"""Auth routes — register / login / logout + the auth-gate. OWNER: Lior (F1).

Course-mandated: passwords hashed with werkzeug; protected endpoints auth-gated; input validated
(NoSQL-injection-safe — non-string credentials are rejected before any query). The user store is
injected (``app.config["USERS"]`` — the web->db seam: ``.get`` / ``.add``), so this layer is
unit-tested with an in-memory fake and runs without Mongo.
"""
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, current_app, jsonify, request, session
from itsdangerous import BadData, URLSafeTimedSerializer
from werkzeug.security import check_password_hash, generate_password_hash

from ratelimit import limiter
from services.email import send_email
from services.identity import display_name

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

USERNAME_MIN, USERNAME_MAX = 3, 64
PASSWORD_MIN, PASSWORD_MAX = 8, 256
EMAIL_MAX = 254
# Pragmatic email check (one @, a dot in the domain, no spaces); the string-type check is also the
# NoSQL-injection gate. Full RFC-5322 validation isn't the goal — a real send confirms deliverability.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Identical body for both login-failure modes -> no user-enumeration (DESIGN §5).
_INVALID_LOGIN = {"error": "invalid username or password"}

# Verified on the user-missing login path so a miss costs the same as a real check -> no timing
# oracle for user-enumeration (DESIGN §5). Computed once at import; not a real credential.
_DECOY_HASH = generate_password_hash("not-a-real-secret-timing-decoy")


def validate_credentials(data):
    """Return ``(username, password)`` for a well-formed credential payload, else raise ``ValueError``.

    Valid = a JSON object whose ``username`` and ``password`` are plain strings within length
    bounds. The string-type check is the NoSQL-injection gate: a payload like
    ``{"username": {"$gt": ""}}`` is rejected here, before it can ever reach a query.
    """
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object with username and password")
    username = data.get("username")
    password = data.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        raise ValueError("username and password must be strings")
    username = username.strip()
    if not USERNAME_MIN <= len(username) <= USERNAME_MAX:
        raise ValueError(f"username must be {USERNAME_MIN}-{USERNAME_MAX} characters")
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise ValueError(f"password must be {PASSWORD_MIN}-{PASSWORD_MAX} characters")
    return username, password


def validate_email(value):
    """Return a normalised (stripped, lower-cased) email for a well-formed address, else ``ValueError``."""
    if not isinstance(value, str):
        raise ValueError("email must be a string")
    value = value.strip().lower()
    if not 3 <= len(value) <= EMAIL_MAX or not _EMAIL_RE.match(value):
        raise ValueError("enter a valid email address")
    return value


def validate_display_name(value):
    """Return a clean (stripped) display name for a well-formed value, else raise ``ValueError``.

    Same length bounds as a registration name; the string-type check is the NoSQL-injection gate (a
    ``{"$gt": ""}`` object is rejected before it can reach a query). A display name need NOT be unique.
    """
    if not isinstance(value, str):
        raise ValueError("display name must be a string")
    value = value.strip()
    if not USERNAME_MIN <= len(value) <= USERNAME_MAX:
        raise ValueError(f"display name must be {USERNAME_MIN}-{USERNAME_MAX} characters")
    return value


def login_required(view):
    """Auth-gate: respond 401 unless a user is logged in. Reusable by /profile, /dashboard, ..."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return jsonify(error="authentication required"), 401
        return view(*args, **kwargs)

    return wrapped


def _users():
    return current_app.config["USERS"]


@auth_bp.get("/auth/config")
def auth_config():
    """Public: credential bounds + the auth modes (email live/mock, login-OTP, signup-verify), so the UI
    and the dev-tools panel read requirements + the current mode from one source of truth. No secrets."""
    return jsonify(username_min=USERNAME_MIN, username_max=USERNAME_MAX,
                   password_min=PASSWORD_MIN, password_max=PASSWORD_MAX,
                   email_mode="live" if current_app.config.get("SMTP_HOST") else "mock",
                   otp_login=_otp_active(), verify_email=_register_verify_active()), 200


# The display name people choose need NOT be unique (many "Alex"es). Each account still gets a UNIQUE
# internal handle — what every collection keys on — so identity, ownership and addressing stay
# unambiguous. First to claim a name gets it bare; later ones get a -2/-3 suffix. The email is the
# unique login identity; the handle is never shown (display_name is).
HANDLE_MAX_SUFFIX = 10000


def _allocate_handle(display, password_hash, email):
    """Register `display` under a fresh unique handle and return it, or None if none was free.

    ``_users().add`` is the atomic gate — False iff the handle is taken — so a collision just tries the
    next suffix. The password is hashed once by the caller (not per attempt)."""
    for suffix in range(1, HANDLE_MAX_SUFFIX + 1):
        handle = display if suffix == 1 else f"{display}-{suffix}"
        if _users().add(handle, password_hash, email, display_name=display):
            return handle
    return None


@auth_bp.post("/register")
@limiter.limit("10 per minute")   # anti-spam: bulk account creation from one IP
def register():
    data = request.get_json(silent=True)
    try:
        display, password = validate_credentials(data)   # the submitted "username" IS the display name
        email = validate_email(data.get("email") if isinstance(data, dict) else None)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    try:
        if _users().by_email(email):                      # one email -> one account (login identity)
            return jsonify(error="an account with this email already exists"), 409
        pw_hash = generate_password_hash(password)
        if _register_verify_active():
            # Don't create the account yet: email a code and only create it once the address is CONFIRMED,
            # so a user can't register with a fake or someone else's email. The pending signup lives in the
            # session (this browser), never in the DB, until /register/verify.
            dev_code = _issue_reg_code(display, pw_hash, email)
            body = {"status": "verify_required", "email": email, "expires_in": current_app.config["OTP_TTL_SECONDS"]}
            if dev_code is not None:                       # no SMTP -> surface the code (dev/grading)
                body["dev_code"] = dev_code
            return jsonify(body), 200
        handle = _allocate_handle(display, pw_hash, email)
    except Exception:
        logger.exception("user store unavailable during register")
        return jsonify(error="user store unavailable"), 503
    if handle is None:                                    # every suffix taken (pathological) -> transient
        return jsonify(error="could not create the account — please try again"), 503
    return jsonify(status="registered", username=handle, display_name=display), 201


@auth_bp.post("/register/verify")
@limiter.limit("10 per minute")
def register_verify():
    """Second registration step: confirm the emailed code, THEN create the account and log the user straight
    in (a verified code proves email ownership). The pending signup comes from the SESSION, never the body."""
    pending = session.get("pending_reg")
    if not pending:
        return jsonify(error="no registration in progress — please start again"), 400
    data = request.get_json(silent=True) or {}
    code = data.get("code")
    if not isinstance(code, str):
        return jsonify(error="enter the 6-digit code from your email"), 400
    if time.time() > pending.get("expires", 0):
        session.pop("pending_reg", None)
        return jsonify(error="this code has expired — please register again"), 400
    if pending.get("attempts", 0) >= current_app.config["OTP_MAX_ATTEMPTS"]:
        session.pop("pending_reg", None)
        return jsonify(error="too many attempts — please register again"), 429
    if not check_password_hash(pending["code_hash"], code.strip()):
        pending["attempts"] = pending.get("attempts", 0) + 1
        session["pending_reg"] = pending                   # persist the bumped attempt count
        return jsonify(error="that code isn't right — check your email and try again"), 400
    try:
        if _users().by_email(pending["email"]):            # a race: the email got registered while pending
            session.pop("pending_reg", None)
            return jsonify(error="an account with this email already exists"), 409
        handle = _allocate_handle(pending["display"], pending["pw_hash"], pending["email"])
    except Exception:
        logger.exception("user store unavailable during register verify")
        return jsonify(error="user store unavailable"), 503
    if handle is None:
        return jsonify(error="could not create the account — please try again"), 503
    session.clear()
    session["username"] = handle                           # verified email == proof of ownership -> sign in
    return jsonify(status="registered", username=handle, display_name=pending["display"]), 201


@auth_bp.post("/register/resend")
@limiter.limit("5 per minute")
def register_resend():
    """Re-issue the registration code from the pending session (nothing is re-sent from the client)."""
    pending = session.get("pending_reg")
    if not pending:
        return jsonify(error="no registration in progress — please start again"), 400
    dev_code = _issue_reg_code(pending["display"], pending["pw_hash"], pending["email"])
    body = {"status": "code_sent", "expires_in": current_app.config["OTP_TTL_SECONDS"]}
    if dev_code is not None:
        body["dev_code"] = dev_code
    return jsonify(body), 200


@auth_bp.post("/login")
@limiter.limit("20 per minute")   # anti-brute-force: password guessing from one IP
def login():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="expected a JSON object with username and password"), 400
    identifier, password = data.get("username"), data.get("password")
    # String-type gate = the NoSQL-injection defense: a {"$gt": ""} payload is rejected here, before
    # it can reach a lookup. Login doesn't length-check the identifier (an email is longer than a
    # username) — a bad identifier just falls through to the generic invalid-login below.
    if not isinstance(identifier, str) or not isinstance(password, str):
        return jsonify(error="username and password must be strings"), 400
    identifier = identifier.strip()
    username = identifier
    try:
        if "@" in identifier:                      # let users sign in with their registered email too
            username = _users().by_email(identifier.lower()) or identifier
        user = _users().get(username)
    except Exception:
        logger.exception("user store unavailable during login")
        return jsonify(error="user store unavailable"), 503
    stored_hash = user.get("password_hash") if isinstance(user, dict) else None
    if not isinstance(stored_hash, str):
        check_password_hash(_DECOY_HASH, password)  # equalize work with the found-user path
        return jsonify(_INVALID_LOGIN), 401
    if not check_password_hash(stored_hash, password):
        return jsonify(_INVALID_LOGIN), 401

    # Password verified. Log in now UNLESS 2-step OTP is active AND this browser isn't already trusted.
    if _otp_active() and not _remember_cookie_valid(username, stored_hash):
        try:
            session.clear()
            session["pending_otp_user"] = username     # binds the challenge to THIS browser session
            dev_code = _issue_otp(username, user.get("email"))
        except Exception:
            logger.exception("failed to issue login OTP")
            return jsonify(error="could not start verification — please try again"), 503
        body = {"status": "otp_required", "username": username,
                "expires_in": current_app.config["OTP_TTL_SECONDS"]}   # so the UI can count down to expiry
        if dev_code is not None:                       # no SMTP configured -> surface the code (dev/grading)
            body["dev_otp"] = dev_code
        return jsonify(body), 200

    session.clear()
    session["username"] = username
    return jsonify(status="logged in", username=username, display_name=display_name(username)), 200


@auth_bp.post("/verify-otp")
def verify_otp():
    """Second login step: exchange the emailed code for a real session.

    The pending user comes from the SESSION (set by /login), never the request body — so a leaked code
    can only complete the login it was issued for, on the browser that started it. The code is checked
    against the stored HASH; wrong guesses increment an atomic counter and lock out at OTP_MAX_ATTEMPTS;
    an expired challenge is cleared. On success the session is promoted and, if the user opted in, a
    signed 'remember this browser' cookie is set so the next login skips OTP.
    """
    username = session.get("pending_otp_user")
    if not username:
        return jsonify(error="no verification in progress — please log in again"), 400
    data = request.get_json(silent=True) or {}
    code = data.get("code")
    if not isinstance(code, str):
        return jsonify(error="enter the 6-digit code from your email"), 400
    code = code.strip()

    max_attempts = current_app.config["OTP_MAX_ATTEMPTS"]
    try:
        challenge = _users().get_otp(username)
    except Exception:
        logger.exception("user store unavailable during otp verify")
        return jsonify(error="user store unavailable"), 503
    if not challenge:
        session.pop("pending_otp_user", None)
        return jsonify(error="no verification in progress — please log in again"), 400
    if time.time() > challenge["expires_at"]:
        _users().clear_otp(username)
        session.pop("pending_otp_user", None)
        return jsonify(error="that code has expired — please log in again"), 400
    if challenge["attempts"] >= max_attempts:
        _users().clear_otp(username)
        session.pop("pending_otp_user", None)
        return jsonify(error="too many attempts — please log in again"), 429
    if not check_password_hash(challenge["otp_hash"], code):
        attempts = _users().bump_otp_attempts(username)
        if attempts >= max_attempts:
            _users().clear_otp(username)
            session.pop("pending_otp_user", None)
            return jsonify(error="too many attempts — please log in again"), 429
        return jsonify(error="incorrect code", attempts_left=max(0, max_attempts - attempts)), 401

    # Correct — consume the one-time challenge and promote the pending session to a real login.
    _users().clear_otp(username)
    try:
        stored_hash = (_users().get(username) or {}).get("password_hash") or ""
    except Exception:
        stored_hash = ""
    session.clear()
    session["username"] = username
    resp = jsonify(status="logged in", username=username, display_name=display_name(username))
    if data.get("remember"):
        _set_remember_cookie(resp, username, stored_hash)
    return resp, 200


@auth_bp.post("/resend-otp")
@limiter.limit("5 per minute")   # a fresh code is rare; cap resends (the UI also gates it to 1 / 30s)
def resend_otp():
    """Re-issue the login code for the verification already in progress — a fresh code with a reset TTL
    and attempt counter. The pending user comes from the SESSION (never the body), so a caller can only
    resend a challenge they themselves started, on the browser that started it."""
    username = session.get("pending_otp_user")
    if not username:
        return jsonify(error="no verification in progress — please log in again"), 400
    try:
        user = _users().get(username) or {}
        dev_code = _issue_otp(username, user.get("email"))
    except Exception:
        logger.exception("failed to resend login OTP")
        return jsonify(error="could not resend the code — please try again"), 503
    body = {"status": "otp_sent", "expires_in": current_app.config["OTP_TTL_SECONDS"]}
    if dev_code is not None:              # dev/no-SMTP: surface the fresh code like /login does
        body["dev_otp"] = dev_code
    return jsonify(body), 200


@auth_bp.post("/logout")
def logout():
    session.clear()
    resp = jsonify(status="logged out")
    resp.delete_cookie(REMEMBER_COOKIE)   # drop trust in this browser -> next login re-verifies via OTP
    return resp, 200


@auth_bp.get("/me")
@login_required
def me():
    handle = session["username"]
    try:
        return jsonify(username=handle, display_name=display_name(handle),
                       email_consent=_users().get_email_consent(handle)), 200
    except Exception:
        logger.exception("user store unavailable during /me")
        return jsonify(error="user store unavailable"), 503


# ---- account settings (change the shown name / the password, from inside the app) ----
@auth_bp.post("/account/display-name")
@limiter.limit("20 per minute")   # light cap on rename churn
@login_required
def change_display_name():
    """Change the caller's (non-unique) display name. The internal handle — what every collection keys
    on — is untouched, so ownership / DM addressing / history are unaffected; only the shown name changes."""
    data = request.get_json(silent=True)
    try:
        new_name = validate_display_name(data.get("display_name") if isinstance(data, dict) else None)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    try:
        _users().set_display_name(session["username"], new_name)
    except Exception:
        logger.exception("user store unavailable during display-name change")
        return jsonify(error="user store unavailable"), 503
    return jsonify(status="display name updated", display_name=new_name), 200


@auth_bp.post("/account/password")
@limiter.limit("10 per minute")   # a hijacked, unlocked session must not brute-force the current password
@login_required
def change_password():
    """Change the caller's password. Requires the CURRENT password, so an attacker on a hijacked session
    can't silently take the account over. Re-hashing invalidates every 'remember this browser' cookie
    (they embed the old hash tail) -> OTP is required again on the next login everywhere; this browser's
    remember cookie is also dropped now. The current session stays logged in (the user just re-proved it)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="expected a JSON object"), 400
    current_password, new_password = data.get("current_password"), data.get("new_password")
    if not isinstance(current_password, str) or not isinstance(new_password, str):
        return jsonify(error="current and new passwords must be strings"), 400
    if not PASSWORD_MIN <= len(new_password) <= PASSWORD_MAX:
        return jsonify(error=f"new password must be {PASSWORD_MIN}-{PASSWORD_MAX} characters"), 400
    username = session["username"]
    try:
        user = _users().get(username)
    except Exception:
        logger.exception("user store unavailable during password change")
        return jsonify(error="user store unavailable"), 503
    stored_hash = user.get("password_hash") if isinstance(user, dict) else None
    if not isinstance(stored_hash, str) or not check_password_hash(stored_hash, current_password):
        return jsonify(error="current password is incorrect"), 403
    try:
        _users().set_password(username, generate_password_hash(new_password))
    except Exception:
        logger.exception("user store unavailable during password change")
        return jsonify(error="user store unavailable"), 503
    resp = jsonify(status="password updated")
    resp.delete_cookie(REMEMBER_COOKIE)   # this browser must re-verify via OTP on its next login too
    return resp, 200


@auth_bp.post("/account/email-consent")
@limiter.limit("30 per minute")
@login_required
def change_email_consent():
    """Record the caller's opt-in/out for NON-ESSENTIAL email. Security email (login OTP, password
    reset) is transactional and unaffected by this — it is always sent."""
    data = request.get_json(silent=True)
    consent = data.get("consent") if isinstance(data, dict) else None
    if not isinstance(consent, bool):
        return jsonify(error="consent must be true or false"), 400
    try:
        _users().set_email_consent(session["username"], consent)
    except Exception:
        logger.exception("user store unavailable during email-consent change")
        return jsonify(error="user store unavailable"), 503
    return jsonify(status="email preferences updated", email_consent=consent), 200


@auth_bp.get("/account/export")
@limiter.limit("10 per minute")
@login_required
def export_data():
    """GDPR data portability: return ALL of the caller's data as a JSON download — everything the app
    holds about them, minus the password hash. Served as an attachment so the browser saves a file."""
    username = session["username"]
    cfg = current_app.config
    try:
        user = _users().get(username) or {}
        data = {
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "account": {"username": username, "display_name": user.get("display_name"),
                        "email": user.get("email"), "email_consent": _users().get_email_consent(username)},
            "profile": cfg["PROFILES"].get(username),
            "history": cfg["HISTORY"].list(username),
            "forum": cfg["FORUM"].export_user(username),
            "messages": cfg["MESSAGES"].export_for_user(username),
            "notifications": cfg["NOTIFICATIONS"].list(username),
        }
    except Exception:
        logger.exception("data export failed for %s", username)
        return jsonify(error="could not export your data — please try again"), 503
    resp = jsonify(data)
    resp.headers["Content-Disposition"] = 'attachment; filename="worksmarter-export.json"'
    return resp, 200


@auth_bp.delete("/account")
@limiter.limit("5 per minute")   # destructive + irreversible -> cap attempts
@login_required
def delete_account():
    """GDPR right to erasure: verify the password, then delete the user AND all their personal data
    across every store (profile, history, forum content, DMs, notifications), end the session and drop
    the cookies. Irreversible. The identity record is removed LAST, so a mid-cascade store failure leaves
    a still-recoverable, retryable account rather than data orphaned under a deleted handle."""
    data = request.get_json(silent=True)
    password = data.get("password") if isinstance(data, dict) else None
    if not isinstance(password, str):
        return jsonify(error="your password is required to delete your account"), 400
    username = session["username"]
    cfg = current_app.config
    try:
        user = _users().get(username)
    except Exception:
        logger.exception("user store unavailable during account deletion")
        return jsonify(error="user store unavailable"), 503
    stored_hash = user.get("password_hash") if isinstance(user, dict) else None
    if not isinstance(stored_hash, str) or not check_password_hash(stored_hash, password):
        return jsonify(error="password is incorrect"), 403
    try:
        cfg["PROFILES"].delete(username)
        cfg["HISTORY"].delete(username)
        cfg["FORUM"].purge_user(username)
        cfg["MESSAGES"].delete_for_user(username)
        cfg["NOTIFICATIONS"].delete_for_user(username)
        _users().delete(username)                        # remove the identity record LAST
    except Exception:
        logger.exception("account deletion failed mid-cascade for %s", username)
        return jsonify(error="could not delete the account — please try again"), 503
    session.clear()
    resp = jsonify(status="account deleted")
    resp.delete_cookie(REMEMBER_COOKIE)
    return resp, 200


# ---- password reset (forgot-password) ----
_RESET_SALT = "pw-reset-v1"


def _reset_serializer():
    # Signed, self-expiring token -> no server-side reset state to store or leak. It embeds the tail of
    # the password hash at issue time, so once the password changes the token stops validating (single-use).
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_RESET_SALT)


@auth_bp.post("/forgot-password")
def forgot_password():
    """Email a reset link for a registered address. ALWAYS 200 with the same body -> no account
    enumeration (a caller can't tell whether the email is registered)."""
    data = request.get_json(silent=True)
    email = data.get("email") if isinstance(data, dict) else None
    body = {"status": "if that email is registered, a reset link is on its way"}
    if not isinstance(email, str):
        return jsonify(body), 200
    email = email.strip().lower()
    try:
        username = _users().by_email(email)
    except Exception:
        logger.exception("user store unavailable during forgot-password")
        return jsonify(body), 200
    if username:
        user = _users().get(username)
        token = _reset_serializer().dumps({"u": username, "h": (user.get("password_hash") or "")[-16:]})
        link = current_app.config["APP_BASE_URL"].rstrip("/") + "/?reset_token=" + token
        minutes = current_app.config["RESET_TOKEN_MAX_AGE"] // 60
        send_email(current_app.config, email, "Reset your Work Smarter, Not Harder password",
                   f"Reset your password with this link (valid {minutes} min):\n\n{link}\n\n"
                   "If you didn't request this, you can ignore this email.")
        if not current_app.config.get("SMTP_HOST"):    # dev/mock (log backend): surface the link like dev_otp
            body["dev_reset_link"] = "/?reset_token=" + token   # RELATIVE -> the click stays on the current host
    # In real (SMTP) mode the body is IDENTICAL whether or not the email was registered -> no account
    # enumeration, and the link goes out solely by email. `dev_reset_link` appears ONLY with the log backend
    # (local dev / grading), where surfacing it on-screen makes the reset flow testable with no inbox.
    return jsonify(body), 200


@auth_bp.post("/reset-password")
def reset_password():
    """Set a new password from a valid, unexpired reset token (single-use — see ``_reset_serializer``)."""
    data = request.get_json(silent=True) or {}
    token, password = data.get("token"), data.get("password")
    if (not isinstance(token, str) or not isinstance(password, str)
            or not PASSWORD_MIN <= len(password) <= PASSWORD_MAX):
        return jsonify(error=f"a valid link and a {PASSWORD_MIN}-{PASSWORD_MAX} character password are required"), 400
    try:
        payload = _reset_serializer().loads(token, max_age=current_app.config["RESET_TOKEN_MAX_AGE"])
    except BadData:
        return jsonify(error="this reset link is invalid or has expired"), 400
    username = payload.get("u")
    try:
        user = _users().get(username) if username else None
    except Exception:
        logger.exception("user store unavailable during reset")
        return jsonify(error="user store unavailable"), 503
    if not user or (user.get("password_hash") or "")[-16:] != payload.get("h"):
        return jsonify(error="this reset link is invalid or has expired"), 400
    try:
        _users().set_password(username, generate_password_hash(password))
    except Exception:
        logger.exception("user store unavailable during reset")
        return jsonify(error="user store unavailable"), 503
    return jsonify(status="password updated — you can log in now"), 200


# ---- login OTP + "remember this browser" (2-step verification) ----
OTP_LENGTH = 6
REMEMBER_COOKIE = "remember_token"
_REMEMBER_SALT = "remember-browser-v1"   # distinct from the reset salt -> tokens aren't interchangeable


def _otp_active():
    """True when 2-step email OTP should gate logins: enabled AND not under the test harness. The login
    test suite asserts the classic one-step flow, so ``TESTING`` turns OTP off; the dedicated 2FA tests
    run with TESTING off + OTP on. A valid remember-this-browser cookie still skips OTP per login."""
    cfg = current_app.config
    return bool(cfg.get("OTP_ENABLED")) and not cfg.get("TESTING")


def _register_verify_active():
    """True when registration must confirm the email first (enabled AND not under the test harness). The
    register-then-login test suite relies on instant creation, so ``TESTING`` turns it off; the dedicated
    verification tests run with TESTING off + the flag on. Mirrors ``_otp_active``."""
    cfg = current_app.config
    return bool(cfg.get("REGISTER_VERIFY_EMAIL")) and not cfg.get("TESTING")


def _issue_reg_code(display, pw_hash, email):
    """Start email verification for a NEW signup: stash the pending account in the SESSION (this browser,
    never the DB) with a hashed code + TTL, email the code, and return the plaintext ONLY when no SMTP is
    configured (dev/grading surfacing). Reuses the OTP TTL/length."""
    code = f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"
    ttl = current_app.config["OTP_TTL_SECONDS"]
    session["pending_reg"] = {"display": display, "email": email, "pw_hash": pw_hash,
                              "code_hash": generate_password_hash(code), "expires": time.time() + ttl, "attempts": 0}
    minutes = max(1, ttl // 60)
    send_email(current_app.config, email, "Confirm your Work Smarter, Not Harder email",
               f"Your Work Smarter, Not Harder confirmation code is: {code}\n\n"
               f"Enter it to finish creating your account. It expires in {minutes} min.\n"
               "If you didn't request this, you can ignore this email.")
    return None if current_app.config.get("SMTP_HOST") else code


def _issue_otp(username, email):
    """Generate a fresh code, store it HASHED with a TTL (attempts reset), and deliver it.

    Returns the plaintext code ONLY when no SMTP is configured — the dev/log backend, where surfacing
    the code on-screen and in the logs makes grading and teammate testing trivial. When SMTP IS set the
    code leaves solely by real email and this returns None (never surfaced)."""
    code = f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"
    ttl = current_app.config["OTP_TTL_SECONDS"]
    _users().set_otp(username, generate_password_hash(code), time.time() + ttl)
    minutes = max(1, ttl // 60)
    send_email(current_app.config, email or "(no email on file)", "Your Work Smarter, Not Harder login code",
               f"Your Work Smarter, Not Harder login code is: {code}\n\n"
               f"It expires in {minutes} min. If this wasn't you, you can ignore this email.")
    return None if current_app.config.get("SMTP_HOST") else code


def _remember_serializer():
    # Signed cookie proving this browser already passed OTP. Embeds the password-hash tail, so a password
    # change (or reset) silently invalidates every trusted browser and forces OTP again.
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_REMEMBER_SALT)


def _remember_cookie_valid(username, stored_hash):
    """True iff the request carries a valid, unexpired remember cookie for THIS user whose embedded
    password-hash tail still matches (a since-changed password -> mismatch -> OTP required again)."""
    token = request.cookies.get(REMEMBER_COOKIE)
    if not token:
        return False
    try:
        payload = _remember_serializer().loads(token, max_age=current_app.config["REMEMBER_COOKIE_MAX_AGE"])
    except BadData:
        return False
    return payload.get("u") == username and payload.get("h") == (stored_hash or "")[-16:]


def _set_remember_cookie(resp, username, stored_hash):
    """Set the signed, HttpOnly remember-this-browser cookie (Secure mirrors the session cookie)."""
    token = _remember_serializer().dumps({"u": username, "h": (stored_hash or "")[-16:]})
    resp.set_cookie(REMEMBER_COOKIE, token, max_age=current_app.config["REMEMBER_COOKIE_MAX_AGE"],
                    httponly=True, samesite="Lax",
                    secure=bool(current_app.config.get("SESSION_COOKIE_SECURE")))
