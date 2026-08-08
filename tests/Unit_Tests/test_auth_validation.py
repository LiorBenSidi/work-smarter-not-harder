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
    """A legitimate credential pair passes and comes back as the cleaned values the caller goes on to use — the gate must not lock out real users."""
    assert validate({"username": "alice", "password": "s3cretpw!"}) == ("alice", "s3cretpw!")


def test_strips_surrounding_whitespace_on_username(validate):
    """Whitespace around a username is trimmed, so someone who copy-pastes their handle is not told it does not exist."""
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
    """A body that is not a JSON object, or that is missing either credential, is rejected before any query is built."""
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
    """A Mongo operator object, a list, or a number sent where a string belongs is refused — this is the wall that stops a query document being smuggled in through the credential fields."""
    with pytest.raises(ValueError):
        validate(injection)


@pytest.mark.parametrize("username", ["", "  ", "ab"])  # empty / whitespace-only / too short (<3)
def test_rejects_bad_username_length(validate, username):
    """An empty, whitespace-only, or too-short username is refused rather than creating an account nobody can address."""
    with pytest.raises(ValueError):
        validate({"username": username, "password": "s3cretpw!"})


def test_rejects_overlong_username(validate):
    """An oversized username is refused, so one caller cannot park an unbounded string in the account handle."""
    with pytest.raises(ValueError):
        validate({"username": "a" * 65, "password": "s3cretpw!"})


@pytest.mark.parametrize("password", ["a" * 7])   # exactly one character under the minimum
def test_rejects_too_short_password(validate, password):
    """A password one character under the minimum is refused at registration, which is the only moment the rule can be enforced.

    The value is the BOUNDARY (min - 1), not merely a short string. `""` and `"short"` are both far
    below the floor, so they are refused by any minimum from 1 upwards: with them as the only cases,
    lowering PASSWORD_MIN from 8 to 7 left the entire suite green (measured: 1082 passed), i.e. the
    documented minimum was pinned by nothing. Seven characters fails if and only if the floor is 8.
    """
    with pytest.raises(ValueError):
        validate({"username": "alice", "password": password})


def test_rejects_overlong_password(validate):
    """An oversized password is refused before it reaches the hashing function, whose cost grows with the length of its input."""
    with pytest.raises(ValueError):
        validate({"username": "alice", "password": "a" * 257})


@pytest.mark.parametrize("username", ["abc", "a" * 64])  # exact min / max are ACCEPTED (pins the <= bounds)
def test_accepts_username_length_boundaries(validate, username):
    """The exact minimum and maximum lengths are ACCEPTED, pinning both bounds as inclusive so an off-by-one cannot quietly lock out the edge cases."""
    accepted, _ = validate({"username": username, "password": "s3cretpw!"})
    assert accepted == username


@pytest.mark.parametrize("password", ["a" * 8, "a" * 256])  # exact min / max are ACCEPTED
def test_accepts_password_length_boundaries(validate, password):
    """The exact minimum and maximum password lengths are accepted too, pinning those bounds inclusive on the same principle."""
    _, accepted = validate({"username": "alice", "password": password})
    assert accepted == password


def test_rejects_null_password(validate):
    """A JSON null arrives as None, which is not a string, so it is refused before any query rather than being compared as if it were a value."""
    with pytest.raises(ValueError):
        validate({"username": "alice", "password": None})


def test_rejects_control_chars_in_username(validate):
    """Newlines and control characters in a field that is later logged and rendered would permit log injection and display tricks, so they are refused at the gate."""
    with pytest.raises(ValueError):
        validate({"username": "ab\ncd evilrow", "password": "s3cretpw!"})


def test_rejects_control_chars_in_display_name(auth_module):
    """The same control-character rule covers the display name, which is shown to other users and written into logs."""
    with pytest.raises(ValueError):
        auth_module.validate_display_name("foo\r\nINJECTED 200 OK")
