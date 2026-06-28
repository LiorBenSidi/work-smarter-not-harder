"""Shared web-suite fixtures.

`web/` is not an installed package, so we exec `web/app.py` off disk (same loader the smoke test
uses). The web layer is built test-first against injected stores — `FakeUsers` / `FakeProfiles` are
in-memory stand-ins for Elad's data layer (the `web -> db` seam is just `.get` / `.add` / `.save`),
so the whole layer runs with NO Mongo and NO Docker (Mini-HW3 DI pattern).
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
def make_client(web_app_module):
    """Factory: build a web test client with given user/profile stores (None -> production default)."""

    def _make(users=None, profiles=None):
        extra = {} if profiles is None else {"profiles": profiles}
        app = web_app_module.create_app(users=users, **extra)
        app.config.update(SECRET_KEY="test-secret-key", TESTING=True)
        return app.test_client()

    return _make


@pytest.fixture
def client(make_client, fake_users):
    return make_client(fake_users)


@pytest.fixture
def profile_client(make_client, fake_users, fake_profiles):
    return make_client(fake_users, fake_profiles)
