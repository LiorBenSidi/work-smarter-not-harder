"""Negative tests — the auth surface refuses every malformed / hostile input. OWNER: Elad.

Adversarial-input suite: for each auth entry point, the ways a caller can get it WRONG — wrong types,
missing fields, NoSQL-injection payloads, oversized bodies, missing CSRF, unauthenticated access —
and the exact refusal each one must earn (4xx with a JSON error, never a 5xx, never a silent pass).
In-process on the injected fakes; complements `Security_Tests/test_auth.py` (which proves the happy
path + hashing) by pinning the REJECTION contract.
"""
import pytest


def _signup(c, name="negauth"):
    c.post("/register", json={"username": name, "password": "s3cretpw!", "email": name + "@ex.com"})
    c.post("/login", json={"username": name, "password": "s3cretpw!"})
    return name


# --------------------------------------------------------------- login refusals

@pytest.mark.parametrize("payload", [
    None,                                                    # no JSON body at all
    [],                                                      # not an object
    {},                                                      # missing both fields
    {"username": "nobody"},                                  # missing password
    {"password": "whatever!"},                               # missing username
    {"username": {"$gt": ""}, "password": {"$gt": ""}},      # NoSQL injection objects
    {"username": 42, "password": True},                      # wrong primitive types
])
def test_login_rejects_malformed_payloads(client, payload):
    r = client.post("/login", json=payload)
    assert 400 <= r.status_code < 500, f"{payload!r} must be refused, got {r.status_code}"
    assert "error" in r.get_json()


def test_login_rejects_wrong_password_and_unknown_user_alike(client):
    _signup(client)
    client.post("/logout")
    assert client.post("/login", json={"username": "negauth", "password": "WRONG-pass1"}).status_code == 401
    assert client.post("/login", json={"username": "ghost", "password": "whatever1!"}).status_code == 401


# --------------------------------------------------------------- register refusals

@pytest.mark.parametrize("payload", [
    {"username": "ab", "password": "s3cretpw!", "email": "a@ex.com"},          # username too short (<3)
    {"username": "x" * 65, "password": "s3cretpw!", "email": "a@ex.com"},      # username too long (>64)
    {"username": "okname", "password": "short1", "email": "a@ex.com"},         # password too short (<8)
    {"username": "okname", "password": "s3cretpw!", "email": "not-an-email"},  # invalid email
    {"username": "okname", "password": "s3cretpw!"},                           # email missing
    {"username": {"$ne": None}, "password": "s3cretpw!", "email": "a@ex.com"}, # injection object
    {"username": "okname", "password": ["s3cretpw!"], "email": "a@ex.com"},    # wrong type
    None,
])
def test_register_rejects_malformed_payloads(client, payload):
    r = client.post("/register", json=payload)
    assert 400 <= r.status_code < 500, f"{payload!r} must be refused, got {r.status_code}"


def test_register_refuses_a_duplicate_email(client):
    ok = client.post("/register", json={"username": "first", "password": "s3cretpw!", "email": "dup@ex.com"})
    assert ok.status_code in (200, 201)
    dup = client.post("/register", json={"username": "second", "password": "s3cretpw!", "email": "dup@ex.com"})
    assert dup.status_code == 409


# --------------------------------------------------------------- the auth gate itself

@pytest.mark.parametrize("method,path", [
    ("GET", "/me"), ("GET", "/dashboard"), ("GET", "/history"), ("GET", "/profile"),
    ("GET", "/forum/posts"), ("GET", "/conversations"), ("GET", "/notifications"),
    ("GET", "/me/engagement"),
    ("POST", "/checkin"), ("POST", "/profile"), ("POST", "/forum/posts"),
    ("POST", "/messages"), ("POST", "/media"),
])
def test_every_protected_route_refuses_anonymous_callers(client, method, path):
    # (/logout is deliberately ungated — an anonymous logout is an idempotent no-op, not a leak.)
    r = client.get(path) if method == "GET" else client.post(path, json={})
    assert r.status_code == 401, f"{method} {path} must demand a login, got {r.status_code}"


# --------------------------------------------------------------- CSRF + body-size hard limits

def test_unsafe_requests_without_the_csrf_token_are_refused(client):
    _signup(client)
    # client.raw bypasses the auto-token wrapper -> a cross-site-shaped POST must bounce with 403.
    r = client.raw.post("/logout", json={})
    assert r.status_code == 403
    assert "CSRF" in r.get_json()["error"]


def test_a_wrong_csrf_token_is_as_dead_as_a_missing_one(client):
    _signup(client)
    r = client.raw.post("/logout", json={}, headers={"X-CSRF-Token": "forged-token-value"})
    assert r.status_code == 403


def test_an_oversized_json_body_is_cut_off_with_413(client):
    # MAX_CONTENT_LENGTH (64 KB) guards every JSON route; the body must die before parsing.
    huge = {"username": "x" * (70 * 1024), "password": "s3cretpw!", "email": "a@ex.com"}
    assert client.post("/register", json=huge).status_code == 413
