"""CSRF protection — double-submit cookie. OWNER: Lior.

State-changing requests (POST/PUT/PATCH/DELETE) must echo, in the ``X-CSRF-Token`` header, the value
of the readable ``csrf_token`` cookie. A cross-site attacker can neither read that cookie
(same-origin) nor set a custom header without a CORS preflight, so a forged request can't produce a
matching pair -> 403. Pairs with SameSite=Lax + the JSON-content-type requirement (defence in depth).

The token is not a secret credential (the session cookie is the credential, and stays HttpOnly +
Secure), so the csrf cookie is intentionally readable by JS and not marked Secure — that keeps it
working over the local HTTP dev server while the real protection comes from same-origin + the header.
"""
import secrets

from flask import jsonify, request

_UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
COOKIE_NAME = "csrf_token"
HEADER_NAME = "X-CSRF-Token"


def init_csrf(app):
    """Register the double-submit CSRF before/after request hooks on `app`."""

    @app.before_request
    def _verify():
        if request.method in _UNSAFE:
            cookie = request.cookies.get(COOKIE_NAME, "")
            header = request.headers.get(HEADER_NAME, "")
            if not cookie or not header or not secrets.compare_digest(cookie, header):
                return jsonify(error="CSRF token missing or invalid"), 403

    @app.after_request
    def _issue(response):
        # Issue a token on first contact; keep it stable across the visit.
        if not request.cookies.get(COOKIE_NAME):
            response.set_cookie(COOKIE_NAME, secrets.token_urlsafe(32), samesite="Lax", httponly=False)
        return response
