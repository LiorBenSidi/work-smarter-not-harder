"""Shared web-suite fixtures.

`web/` is not an installed package, so we exec `web/app.py` off disk (same loader the smoke test
uses). The web layer is built test-first against injected stores — `FakeUsers` / `FakeProfiles` /
`FakeHistory` are in-memory stand-ins for Elad's data layer (the `web -> db` seam is just `.get` /
`.add` / `.save` / `.list`), so the whole layer runs with NO Mongo and NO Docker (Mini-HW3 DI pattern).
"""
import importlib.util
import sys
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
    """In-memory user store — the `web -> db` seam Elad implements for real in db.py.

    Contract: `add` returns False if the username already exists (else stores and returns True);
    `get` returns the stored record dict (with `password_hash`) or None.
    """

    def __init__(self):
        self._by_name = {}

    def get(self, username):
        return self._by_name.get(username)

    def add(self, username, password_hash):
        if username in self._by_name:
            return False
        self._by_name[username] = {"username": username, "password_hash": password_hash}
        return True


class FakeProfiles:
    """In-memory profile store — the `web -> db` seam Elad implements in db.py (.get / .save)."""

    def __init__(self):
        self._by_user = {}

    def get(self, username):
        return self._by_user.get(username)

    def save(self, username, profile):
        self._by_user[username] = profile


class FakeHistory:
    """In-memory analysis-history store — the `web -> db` seam Elad implements in db.py (.list / .add)."""

    def __init__(self):
        self._by_user = {}

    def list(self, username):
        return self._by_user.get(username, [])

    def add(self, username, entry):
        self._by_user.setdefault(username, []).append(entry)


class FakeForum:
    """In-memory forum store — the `web -> db` seam Elad implements in db.py
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
        comment = {"author": author, "body": body}
        post["comments"].append(comment)
        return comment

    def vote(self, post_id, username, value):
        post = self._posts.get(post_id)
        if post is None:
            return None
        post["votes"][username] = value  # one vote per user; re-voting replaces
        post["score"] = sum(post["votes"].values())
        return post["score"]


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

    def _make(users=None, profiles=None, history=None, forum=None):
        extra = {}
        if profiles is not None:
            extra["profiles"] = profiles
        if history is not None:
            extra["history"] = history
        if forum is not None:
            extra["forum"] = forum
        app = web_app_module.create_app(users=users, **extra)
        app.config.update(SECRET_KEY="test-secret-key", TESTING=True)
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
def forum_client(make_client, fake_users, fake_forum):
    return make_client(fake_users, forum=fake_forum)
