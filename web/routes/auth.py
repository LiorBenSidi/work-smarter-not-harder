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
    """Public: the credential bounds, so the UI shows requirements from one source of truth (here)."""
    return jsonify(username_min=USERNAME_MIN, username_max=USERNAME_MAX,
                   password_min=PASSWORD_MIN, password_max=PASSWORD_MAX), 200


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
        handle = _allocate_handle(display, generate_password_hash(password), email)
    except Exception:
        logger.exception("user store unavailable during register")
        return jsonify(error="user store unavailable"), 503
    if handle is None:                                    # every suffix taken (pathological) -> transient
        return jsonify(error="could not create the account — please try again"), 503
    return jsonify(status="registered", username=handle, display_name=display), 201


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
    return jsonify(username=handle, display_name=display_name(handle)), 200


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
        send_email(current_app.config, email, "Reset your Work Smarter password",
                   f"Reset your password with this link (valid {minutes} min):\n\n{link}\n\n"
                   "If you didn't request this, you can ignore this email.")
    # Identical body whether or not the email was registered -> no account enumeration. The link is
    # delivered ONLY by email (same send_email path as the login OTP); it is never returned here.
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


def _issue_otp(username, email):
    """Generate a fresh code, store it HASHED with a TTL (attempts reset), and deliver it.

    Returns the plaintext code ONLY when no SMTP is configured — the dev/log backend, where surfacing
    the code on-screen and in the logs makes grading and teammate testing trivial. When SMTP IS set the
    code leaves solely by real email and this returns None (never surfaced)."""
    code = f"{secrets.randbelow(10 ** OTP_LENGTH):0{OTP_LENGTH}d}"
    ttl = current_app.config["OTP_TTL_SECONDS"]
    _users().set_otp(username, generate_password_hash(code), time.time() + ttl)
    minutes = max(1, ttl // 60)
    send_email(current_app.config, email or "(no email on file)", "Your Work Smarter login code",
               f"Your Work Smarter login code is: {code}\n\n"
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
