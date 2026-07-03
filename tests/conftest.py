"""Shared web-suite fixtures.

`web/` is not an installed package, so we exec `web/app.py` off disk (same loader the smoke test
uses). The web layer is built test-first against injected stores — `FakeUsers` / `FakeProfiles` /
`FakeHistory` are in-memory stand-ins for Lior's data layer (the `web -> db` seam is just `.get` /
`.add` / `.save` / `.list`), so the whole layer runs with NO Mongo and NO Docker (Mini-HW3 DI pattern).
"""
import importlib.util
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"


def _load_web_app():
    """Exec web/app.py with web/ on sys.path (it imports `config` + `routes.*`)."""
    sys.path.insert(0, str(WEB))
    try:
        spec = importlib.util.spec_from_file_location("web_app_under_test", str(WEB / "app.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(WEB))


class FakeUsers:
    """In-memory user store — the `web -> db` seam Lior implements for real in db.py.

    Contract: `add` returns False if the username already exists (else stores and returns True);
    `get` returns the stored record dict (with `password_hash`) or None.
    """

    def __init__(self):
        self._by_name = {}

    def get(self, username):
        return self._by_name.get(username)

    def add(self, username, password_hash, email=None, display_name=None):
        if username in self._by_name:
            return False
        rec = {"username": username, "password_hash": password_hash,
               "display_name": display_name if display_name is not None else username}
        if email is not None:
            rec["email"] = email
        self._by_name[username] = rec
        return True

    def by_email(self, email):
        return next((n for n, r in self._by_name.items() if r.get("email") == email), None)

    def set_password(self, username, password_hash):
        rec = self._by_name.get(username)
        if rec is None:
            return False
        rec["password_hash"] = password_hash
        return True

    def set_display_name(self, username, display_name):
        rec = self._by_name.get(username)
        if rec is None:
            return False
        rec["display_name"] = display_name
        return True

    def delete(self, username):
        return self._by_name.pop(username, None) is not None

    # ---- login-OTP challenge (mirrors db.py set_otp/get_otp/clear_otp/bump_otp_attempts) ----
    def set_otp(self, username, otp_hash, expires_at):
        rec = self._by_name.get(username)
        if rec is None:
            return False
        rec.update(otp_hash=otp_hash, otp_expires_at=expires_at, otp_attempts=0)
        return True

    def get_otp(self, username):
        rec = self._by_name.get(username)
        if not rec or "otp_hash" not in rec:
            return None
        return {"otp_hash": rec["otp_hash"], "expires_at": rec.get("otp_expires_at", 0),
                "attempts": rec.get("otp_attempts", 0)}

    def clear_otp(self, username):
        rec = self._by_name.get(username)
        if rec:
            for key in ("otp_hash", "otp_expires_at", "otp_attempts"):
                rec.pop(key, None)

    def bump_otp_attempts(self, username):
        rec = self._by_name.get(username)
        if not rec or "otp_hash" not in rec:
            return 0
        rec["otp_attempts"] = rec.get("otp_attempts", 0) + 1
        return rec["otp_attempts"]


class FakeProfiles:
    """In-memory profile store — the `web -> db` seam Lior implements in db.py (.get / .save)."""

    def __init__(self):
        self._by_user = {}

    def get(self, username):
        return self._by_user.get(username)

    def save(self, username, profile):
        self._by_user[username] = profile

    def delete(self, username):
        self._by_user.pop(username, None)


class FakeHistory:
    """In-memory analysis-history store — the `web -> db` seam Lior implements in db.py (.list / .add)."""

    def __init__(self):
        self._by_user = {}

    def list(self, username):
        return self._by_user.get(username, [])

    def add(self, username, entry):
        self._by_user.setdefault(username, []).append(entry)

    def delete(self, username):
        self._by_user.pop(username, None)


class FakeForum:
    """In-memory forum store — the `web -> db` seam Lior implements in db.py
    (create_post / list_posts / get_post / add_comment / vote)."""

    def __init__(self):
        self._posts = {}
        self._seq = 0

    def create_post(self, author, title, body, anonymous=False):
        self._seq += 1
        pid = str(self._seq)
        self._posts[pid] = {"id": pid, "author": author, "anonymous": anonymous,
                            "title": title, "body": body, "score": 0, "comments": [], "votes": {}}
        return self._posts[pid]

    def list_posts(self):
        return list(self._posts.values())

    def get_post(self, post_id):
        return self._posts.get(post_id)

    def add_comment(self, post_id, author, body):
        post = self._posts.get(post_id)
        if post is None:
            return None
        self._seq += 1
        comment = {"id": "c" + str(self._seq), "author": author, "body": body, "votes": {}, "score": 0}
        post["comments"].append(comment)
        return {"id": comment["id"], "author": author, "body": body, "score": 0}   # public shape (no votes)

    def vote_comment(self, post_id, comment_id, username, value):
        post = self._posts.get(post_id)
        if post is None:
            return None
        comment = next((c for c in post["comments"] if c.get("id") == comment_id), None)
        if comment is None:
            return None
        comment.setdefault("votes", {})[username] = value  # one vote per user; re-voting replaces
        comment["score"] = sum(comment["votes"].values())
        return comment["score"]

    def vote(self, post_id, username, value):
        post = self._posts.get(post_id)
        if post is None:
            return None
        post["votes"][username] = value  # one vote per user; re-voting replaces
        post["score"] = sum(post["votes"].values())
        return post["score"]

    def update_post(self, post_id, username, title, body):
        post = self._posts.get(post_id)
        if post is None:
            return None
        if post["author"] != username:
            return "forbidden"
        post["title"], post["body"] = title, body
        return post

    def delete_post(self, post_id, username):
        post = self._posts.get(post_id)
        if post is None:
            return None
        if post["author"] != username:
            return "forbidden"
        del self._posts[post_id]
        return True

    def purge_user(self, username):
        # GDPR erasure: drop the user's own posts, then strip their comments + votes (dict-keyed here)
        # out of everyone else's posts, recomputing scores. Mirrors db.forum_purge_user.
        self._posts = {pid: p for pid, p in self._posts.items() if p["author"] != username}
        for p in self._posts.values():
            p["comments"] = [c for c in p["comments"] if c.get("author") != username]
            for c in p["comments"]:
                c.get("votes", {}).pop(username, None)
                c["score"] = sum(c.get("votes", {}).values())
            p["votes"].pop(username, None)
            p["score"] = sum(p["votes"].values())


class FakeMessages:
    """In-memory DM store — mirrors db.py's ``message_*`` seam contract. ``created_at`` is a real epoch
    (so the route's time-based rate limit works) nudged by a counter to keep ordering strict in tests."""

    def __init__(self):
        self._msgs = []
        self._seq = 0

    def _public(self, m):
        return {k: m[k] for k in ("id", "sender", "recipient", "body", "created_at", "read")}

    def send(self, sender, recipient, body):
        self._seq += 1
        m = {"id": str(self._seq), "sender": sender, "recipient": recipient, "body": body,
             "created_at": time.time() + self._seq * 1e-6, "read": False}
        self._msgs.append(m)
        return self._public(m)

    def list_conversation(self, user_a, user_b):
        pair = {user_a, user_b}
        return [self._public(m) for m in self._msgs if {m["sender"], m["recipient"]} == pair]

    def list_conversations(self, user):
        convos = {}
        for m in self._msgs:
            if user not in (m["sender"], m["recipient"]):
                continue
            peer = m["recipient"] if m["sender"] == user else m["sender"]
            row = convos.setdefault(peer, {"peer": peer, "last_message": "", "last_at": 0, "unread": 0})
            row["last_message"], row["last_at"] = m["body"], m["created_at"]
            if m["recipient"] == user and not m["read"]:
                row["unread"] += 1
        return sorted(convos.values(), key=lambda c: c["last_at"], reverse=True)

    def mark_read(self, user, peer):
        for m in self._msgs:
            if m["sender"] == peer and m["recipient"] == user:
                m["read"] = True

    def count_since(self, user, since):
        return sum(1 for m in self._msgs if m["sender"] == user and m["created_at"] >= since)

    def delete_for_user(self, username):
        self._msgs = [m for m in self._msgs if username not in (m["sender"], m["recipient"])]


class FakeNotifications:
    """In-memory notification store — mirrors db.py's ``notification_*`` seam contract."""

    def __init__(self):
        self._items = []
        self._seq = 0

    def _public(self, n):
        return {k: n[k] for k in ("id", "type", "actor", "ref", "text", "created_at", "read")}

    def add(self, user, ntype, actor, ref, text):
        self._seq += 1
        n = {"id": str(self._seq), "user": user, "type": ntype, "actor": actor, "ref": ref,
             "text": text, "created_at": time.time() + self._seq * 1e-6, "read": False}
        self._items.append(n)
        return self._public(n)

    def list(self, user, since=None):
        items = [n for n in self._items if n["user"] == user]
        if since is not None:
            items = [n for n in items if n["created_at"] > since]
        return [self._public(n) for n in sorted(items, key=lambda n: n["created_at"], reverse=True)]

    def mark_read(self, user, ids=None):
        target = set(ids) if ids is not None else None      # [] -> mark nothing, None -> mark all
        for n in self._items:
            if n["user"] == user and (target is None or n["id"] in target):
                n["read"] = True

    def delete_for_user(self, username):
        self._items = [n for n in self._items if n["user"] != username and n.get("actor") != username]


class _CsrfClient:
    """Wraps the Flask test client: seeds the double-submit CSRF cookie (one GET) and auto-sends the
    matching X-CSRF-Token header on unsafe requests, so feature tests don't repeat CSRF plumbing.
    `.raw` exposes the unwrapped client (used by the CSRF-negative tests).
    """

    def __init__(self, flask_client):
        self.raw = flask_client
        self.raw.get("/health")  # issue the csrf cookie

    def _with_token(self, kwargs):
        headers = dict(kwargs.pop("headers", None) or {})
        if "X-CSRF-Token" not in headers:
            cookie = self.raw.get_cookie("csrf_token")
            headers["X-CSRF-Token"] = cookie.value if cookie else ""
        kwargs["headers"] = headers
        return kwargs

    def get(self, *args, **kwargs):
        return self.raw.get(*args, **kwargs)

    def post(self, *args, **kwargs):
        return self.raw.post(*args, **self._with_token(kwargs))

    def put(self, *args, **kwargs):
        return self.raw.put(*args, **self._with_token(kwargs))

    def patch(self, *args, **kwargs):
        return self.raw.patch(*args, **self._with_token(kwargs))

    def delete(self, *args, **kwargs):
        return self.raw.delete(*args, **self._with_token(kwargs))


@pytest.fixture
def web_app_module():
    pytest.importorskip("flask")
    return _load_web_app()


@pytest.fixture
def auth_module(web_app_module):
    # web/app.py imported routes.auth while loading -> it's cached in sys.modules.
    return sys.modules["routes.auth"]


@pytest.fixture
def fake_users():
    return FakeUsers()


@pytest.fixture
def fake_profiles():
    return FakeProfiles()


@pytest.fixture
def fake_history():
    return FakeHistory()


@pytest.fixture
def make_client(web_app_module):
    """Factory: build a web test client with given user/profile/history stores (None -> prod default)."""

    def _make(users=None, profiles=None, history=None, forum=None, messages=None, notifications=None):
        extra = {}
        if profiles is not None:
            extra["profiles"] = profiles
        if history is not None:
            extra["history"] = history
        if forum is not None:
            extra["forum"] = forum
        if messages is not None:
            extra["messages"] = messages
        if notifications is not None:
            extra["notifications"] = notifications
        app = web_app_module.create_app(users=users, **extra)
        # RATELIMIT_ENABLED=False so the suite's many rapid login/register calls aren't throttled; the
        # dedicated rate-limit test flips it back on via the `rate_limited_client` fixture.
        app.config.update(SECRET_KEY="test-secret-key", TESTING=True, RATELIMIT_ENABLED=False)
        return _CsrfClient(app.test_client())

    return _make


@pytest.fixture
def client(make_client, fake_users):
    return make_client(fake_users)


@pytest.fixture
def profile_client(make_client, fake_users, fake_profiles):
    return make_client(fake_users, fake_profiles)


@pytest.fixture
def history_client(make_client, fake_users, fake_history):
    return make_client(fake_users, history=fake_history)


@pytest.fixture
def fake_forum():
    return FakeForum()


@pytest.fixture
def forum_client(make_client, fake_users, fake_forum, fake_notifications):
    # notifications injected too: a vote now pings the post's author, so the forum flow needs a real
    # (fake) notification store — otherwise the best-effort ping would try to resolve Mongo.
    return make_client(fake_users, forum=fake_forum, notifications=fake_notifications)


@pytest.fixture
def fake_messages():
    return FakeMessages()


@pytest.fixture
def fake_notifications():
    return FakeNotifications()


@pytest.fixture
def messages_client(make_client, fake_users, fake_messages, fake_notifications):
    return make_client(fake_users, messages=fake_messages, notifications=fake_notifications)


@pytest.fixture
def make_otp_client(web_app_module):
    """Like make_client but with 2-step login OTP ACTIVE (OTP_ENABLED on, TESTING off — the gate the
    login route reads). SMTP is left unset so the code is dev-surfaced in the /login response, which is
    how the 2FA tests read it. `**overrides` lets a test flip SMTP_HOST / OTP bounds."""

    def _make(users=None, **overrides):
        app = web_app_module.create_app(users=users)
        app.config.update(SECRET_KEY="test-secret-key", TESTING=False, PROPAGATE_EXCEPTIONS=True,
                          OTP_ENABLED=True, SMTP_HOST="", OTP_TTL_SECONDS=600, OTP_MAX_ATTEMPTS=5,
                          REMEMBER_COOKIE_MAX_AGE=30 * 24 * 3600, RATELIMIT_ENABLED=False)
        app.config.update(overrides)
        return _CsrfClient(app.test_client())

    return _make


@pytest.fixture
def rate_limited_client(make_client, fake_users):
    """A client with rate-limiting ACTIVE (make_client disables it for the rest of the suite). Resets the
    limiter's in-memory counters first, since it's a module-level singleton whose per-IP tally would
    otherwise carry across tests."""
    c = make_client(fake_users)
    app = c.raw.application
    app.config["RATELIMIT_ENABLED"] = True
    from ratelimit import limiter
    with app.app_context():
        try:
            limiter.reset()
        except Exception:
            pass
    return c


@pytest.fixture
def otp_client(make_otp_client, fake_users):
    return make_otp_client(fake_users)
