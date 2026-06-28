"""Security tests for CSRF protection (double-submit cookie). OWNER: Lior.

`client` is the CSRF-aware wrapper (auto-sends the matching header); `client.raw` is the unwrapped
Flask test client used to simulate a forged request that lacks / mismatches the token.
"""


def _creds():
    return {"username": "alice", "password": "s3cretpw!"}


def test_unsafe_request_without_token_is_rejected_403(client):
    resp = client.raw.post("/register", json=_creds())  # no X-CSRF-Token header
    assert resp.status_code == 403


def test_mismatched_token_is_rejected_403(client):
    resp = client.raw.post("/register", json=_creds(), headers={"X-CSRF-Token": "not-the-real-token"})
    assert resp.status_code == 403


def test_valid_token_is_accepted(client):
    assert client.post("/register", json=_creds()).status_code == 201  # wrapper sends the matching token


def test_get_requests_need_no_token(client):
    assert client.raw.get("/health").status_code == 200
