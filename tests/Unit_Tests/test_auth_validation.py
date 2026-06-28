"""Unit tests for F1 auth — credential validation (the NoSQL-injection gate). OWNER: Lior.

Spec (independent of the implementation): a credential payload is valid ONLY when it is a JSON
object whose `username` and `password` are plain strings within length bounds. Everything else —
missing keys, non-string values (e.g. a `{"$gt": ""}` injection object), empty / oversized strings —
must be rejected by `validate_credentials` BEFORE any query runs.
"""
import pytest


@pytest.fixture
def validate(auth_module):
    return auth_module.validate_credentials


def test_accepts_a_well_formed_pair(validate):
    assert validate({"username": "alice", "password": "s3cretpw!"}) == ("alice", "s3cretpw!")


def test_strips_surrounding_whitespace_on_username(validate):
    username, _ = validate({"username": "  alice  ", "password": "s3cretpw!"})
    assert username == "alice"


@pytest.mark.parametrize("payload", [
    None,                      # body wasn't JSON at all
    [],                        # not an object
    "alice",                   # not an object
    {"username": "alice"},     # missing password
    {"password": "s3cretpw!"},  # missing username
])
def test_rejects_malformed_payloads(validate, payload):
    with pytest.raises(ValueError):
        validate(payload)


@pytest.mark.parametrize("injection", [
    {"username": {"$gt": ""}, "password": "s3cretpw!"},
    {"username": "alice", "password": {"$ne": None}},
    {"username": {"$regex": ".*"}, "password": {"$exists": True}},
    {"username": ["alice"], "password": "s3cretpw!"},
    {"username": 12345, "password": "s3cretpw!"},
])
def test_rejects_non_string_values_blocking_nosql_injection(validate, injection):
    with pytest.raises(ValueError):
        validate(injection)


@pytest.mark.parametrize("username", ["", "  ", "ab"])  # empty / whitespace-only / too short (<3)
def test_rejects_bad_username_length(validate, username):
    with pytest.raises(ValueError):
        validate({"username": username, "password": "s3cretpw!"})


def test_rejects_overlong_username(validate):
    with pytest.raises(ValueError):
        validate({"username": "a" * 65, "password": "s3cretpw!"})


@pytest.mark.parametrize("password", ["", "short"])  # empty / under 8 chars
def test_rejects_too_short_password(validate, password):
    with pytest.raises(ValueError):
        validate({"username": "alice", "password": password})


def test_rejects_overlong_password(validate):
    with pytest.raises(ValueError):
        validate({"username": "alice", "password": "a" * 257})
