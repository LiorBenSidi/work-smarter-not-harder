"""Auth routes — register / login / logout + the auth-gate. OWNER: Lior (F1).

Course-mandated: passwords hashed with werkzeug; protected endpoints auth-gated; input validated
(NoSQL-injection-safe — non-string credentials are rejected before any query). The user store is
injected (``app.config["USERS"]`` — the web->db seam: ``.get`` / ``.add``), so this layer is
unit-tested with an in-memory fake and runs without Mongo.
"""
import logging
from functools import wraps

from flask import Blueprint, current_app, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)

USERNAME_MIN, USERNAME_MAX = 3, 64
PASSWORD_MIN, PASSWORD_MAX = 8, 256

# Identical body for both login-failure modes -> no user-enumeration (DESIGN §5).
_INVALID_LOGIN = {"error": "invalid username or password"}


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


@auth_bp.post("/register")
def register():
    try:
        username, password = validate_credentials(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    try:
        created = _users().add(username, generate_password_hash(password))
    except Exception:
        logger.exception("user store unavailable during register")
        return jsonify(error="user store unavailable"), 503
    if not created:
        return jsonify(error="username already exists"), 409
    return jsonify(status="registered", username=username), 201


@auth_bp.post("/login")
def login():
    try:
        username, password = validate_credentials(request.get_json(silent=True))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    try:
        user = _users().get(username)
    except Exception:
        logger.exception("user store unavailable during login")
        return jsonify(error="user store unavailable"), 503
    stored_hash = user.get("password_hash") if isinstance(user, dict) else None
    if not isinstance(stored_hash, str) or not check_password_hash(stored_hash, password):
        return jsonify(_INVALID_LOGIN), 401
    session.clear()
    session["username"] = username
    return jsonify(status="logged in", username=username), 200


@auth_bp.post("/logout")
def logout():
    session.clear()
    return jsonify(status="logged out"), 200


@auth_bp.get("/me")
@login_required
def me():
    return jsonify(username=session["username"]), 200
