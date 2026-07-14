"""Unit tests for db/reset_user_data.py. OWNER: Lior.

The reset must clear every DATA collection and NEVER touch `users`, and a dry-run must delete nothing.
Tested against a tiny in-memory fake of the pymongo Database/Collection surface the script uses
(``db[name]``, ``count_documents``, ``delete_many().deleted_count``) — no real Mongo needed.
"""
import importlib.util
from pathlib import Path

RESET_PY = Path(__file__).resolve().parents[2] / "db" / "reset_user_data.py"


def _load():
    spec = importlib.util.spec_from_file_location("reset_user_data", str(RESET_PY))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeResult:
    def __init__(self, n):
        self.deleted_count = n


class _FakeCollection:
    def __init__(self, docs):
        self.docs = list(docs)

    def count_documents(self, _flt):
        return len(self.docs)

    def delete_many(self, _flt):
        n = len(self.docs)
        self.docs = []
        return _FakeResult(n)


class _FakeDb:
    def __init__(self, data):
        self._colls = {name: _FakeCollection(docs) for name, docs in data.items()}

    def __getitem__(self, name):
        return self._colls.setdefault(name, _FakeCollection([]))

    def list_collection_names(self):
        return list(self._colls)


def _seeded_db():
    return _FakeDb({
        "users": [{"username": "elad"}, {"username": "ben.lior"}, {"username": "shiri"}],
        "profiles": [{"username": "elad", "age": 27}],
        "analysis_history": [{"username": "ben.lior"}, {"username": "ben.lior"}],
        "forum_posts": [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}],
        "messages": [{"id": "m1"}],
        "notifications": [{"id": "n1"}, {"id": "n2"}],
    })


def test_apply_clears_every_data_collection():
    mod = _load()
    db = _seeded_db()
    report = mod.reset_user_data(db, apply=True)
    for name in mod.DATA_COLLECTIONS:
        assert db[name].count_documents({}) == 0, f"{name} should be empty after apply"
        assert report[name]["after"] == 0


def test_apply_never_touches_the_users_accounts():
    mod = _load()
    db = _seeded_db()
    mod.reset_user_data(db, apply=True)
    assert db["users"].count_documents({}) == 3           # all three logins survive (incl. elad)
    names = {u["username"] for u in db["users"].docs}
    assert {"elad", "ben.lior", "shiri"} <= names


def test_dry_run_deletes_nothing():
    mod = _load()
    db = _seeded_db()
    report = mod.reset_user_data(db, apply=False)
    assert db["forum_posts"].count_documents({}) == 3     # untouched
    assert db["analysis_history"].count_documents({}) == 2
    assert all(report[name]["deleted"] == 0 for name in mod.DATA_COLLECTIONS)
    assert all(report[name]["after"] == report[name]["before"] for name in mod.DATA_COLLECTIONS)


def test_users_is_not_in_the_clear_list():
    mod = _load()
    # a guard against someone ever adding users to the wipe list
    assert "users" not in mod.DATA_COLLECTIONS
    assert "users" in mod.KEEP_COLLECTIONS


def test_report_counts_are_accurate():
    mod = _load()
    db = _seeded_db()
    report = mod.reset_user_data(db, apply=True)
    assert report["forum_posts"] == {"before": 3, "deleted": 3, "after": 0}
    assert report["messages"] == {"before": 1, "deleted": 1, "after": 0}
    assert report["users"] == {"kept": 3}
