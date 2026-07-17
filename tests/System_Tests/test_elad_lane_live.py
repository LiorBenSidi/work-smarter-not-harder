"""Live cross-feature journey over Elad's lane — media × engagement × upload caps, over REAL HTTP.

The in-process twin (`Integration_Tests/test_elad_lane_journey.py`) proves the features compose;
this proves they compose **through the real stack**: gunicorn, real sockets, the web container's
MEDIA_ROOT volume, and — the part an in-process client physically cannot exercise — the
per-request upload cap rejecting an oversize multipart body at the WSGI layer (Werkzeug reads
`request.max_content_length` against a real Content-Length here, not a test-client construct).

Env-gated on ``E2E_BASE_URL`` (runs in CI's `compose-e2e` against the throwaway stack; skips
cleanly otherwise). Leaves nothing behind: the post is deleted at the end, and the oversize
upload is rejected before its bytes are stored.
"""
import os
import uuid

import pytest

requests = pytest.importorskip("requests")

from _live_auth import TIMEOUT, csrf_headers, sign_in  # noqa: E402  (after importorskip guards `requests`)

BASE = os.environ.get("E2E_BASE_URL", "").rstrip("/")
pytestmark = pytest.mark.skipif(not BASE, reason="set E2E_BASE_URL to run against a live stack")

_PNG = b"\x89PNG\r\n\x1a\nlive-journey-bytes"


def _session():
    s = requests.Session()
    s.get(f"{BASE}/health", timeout=TIMEOUT)   # seed the double-submit CSRF cookie
    return s


def _h(s):
    return csrf_headers(s)


def _login(s, user):
    # Auth-mode-aware: completes verify/OTP when the target stack has them on (#336), so this runs against
    # the CI throwaway stack, a normal `docker compose up` dev stack, or any mock-email deploy.
    sign_in(s, BASE, user, "s3cret-live!")


def test_media_votes_engagement_and_the_upload_cap_over_the_real_wire():
    suffix = uuid.uuid4().hex[:8]
    author, reader = f"lane_a_{suffix}", f"lane_b_{suffix}"

    alice = _session()
    _login(alice, author)
    pid = alice.post(f"{BASE}/forum/posts", json={"title": "live lane", "body": "b"},
                     headers=_h(alice), timeout=TIMEOUT).json()["post"]["id"]
    try:
        cid = alice.post(f"{BASE}/forum/posts/{pid}/comments", json={"body": "mine"},
                         headers=_h(alice), timeout=TIMEOUT).json()["comment"]["id"]

        # upload + bind through the real volume
        up = alice.post(f"{BASE}/media", files={"file": ("p.png", _PNG, "image/png")},
                        headers=_h(alice), timeout=TIMEOUT)
        assert up.status_code == 201, up.text
        mid = up.json()["id"]
        bound = alice.post(f"{BASE}/forum/posts/{pid}/attachments", json={"attachment_ids": [mid]},
                           headers=_h(alice), timeout=TIMEOUT).json()["bound"]
        assert bound == [mid]

        # the oversize body is refused at the WSGI layer — a real Content-Length over MEDIA_MAX_BYTES
        too_big = b"x" * (10 * 1024 * 1024 + 1)   # default cap + 1
        r = alice.post(f"{BASE}/media", files={"file": ("big.png", too_big, "image/png")},
                       headers=_h(alice), timeout=60)
        assert r.status_code == 413, f"oversize upload was not shed: {r.status_code}"
        r = alice.post(f"{BASE}/media", files={"file": ("x.sh", b"#!/bin/sh", "text/x-sh")},
                       headers=_h(alice), timeout=TIMEOUT)
        assert r.status_code == 400, "MIME allowlist did not engage over the wire"

        # a second real user consumes the media and engages
        bob = _session()
        _login(bob, reader)
        served = bob.get(f"{BASE}/media/{mid}", timeout=TIMEOUT)
        assert served.status_code == 200 and served.content == _PNG   # byte-identical through the volume
        assert bob.post(f"{BASE}/forum/posts/{pid}/vote", json={"value": 1},
                        headers=_h(bob), timeout=TIMEOUT).status_code == 200
        assert bob.post(f"{BASE}/forum/posts/{pid}/comments/{cid}/vote", json={"value": 1},
                        headers=_h(bob), timeout=TIMEOUT).status_code == 200
        assert bob.get(f"{BASE}/me/engagement", timeout=TIMEOUT).json() == {"up": 0, "down": 0, "score": 0}

        # the author's personal area reflects exactly that engagement, through the real Mongo
        me = alice.get(f"{BASE}/me/engagement", timeout=TIMEOUT).json()
        assert me == {"up": 2, "down": 0, "score": 2}, me
    finally:
        alice.delete(f"{BASE}/forum/posts/{pid}", headers=_h(alice), timeout=TIMEOUT)
