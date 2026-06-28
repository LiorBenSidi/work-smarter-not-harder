"""Unit tests for the thin core CRUD in web/services/db.py. OWNER: Lior (thin core CRUD).

The data layer is exercised against an in-memory fake collection (the course's mocking technique —
no real Mongo, no Docker), so these pin the *behaviour contract* the web stores depend on:
``get_user`` / ``create_user`` / ``get_profile`` / ``save_profile`` / ``list_history`` and the five
``forum_*`` functions. The fake implements only the pymongo operators db.py uses.
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"


@pytest.fixture
def db_mod():
    pytest.importorskip("pymongo")
    spec = importlib.util.spec_from_file_location("web_db_under_test", str(WEB / "services" / "db.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeColl:
    """Minimal stand-in for a pymongo collection — supports just the ops db.py calls."""

    def __init__(self):
        self.docs = []
        self.indexes = []

    def create_index(self, key, unique=False):
        self.indexes.append((key, unique))

    def _match(self, doc, filt):
        return all(doc.get(k) == v for k, v in filt.items())

    def find_one(self, filt):
        return next((dict(d) for d in self.docs if self._match(d, filt)), None)

    def find(self, filt=None):
        filt = filt or {}
        return [dict(d) for d in self.docs if self._match(d, filt)]

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id="fake")

    def delete_one(self, filt):
        for i, d in enumerate(self.docs):
            if self._match(d, filt):
                del self.docs[i]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    def update_one(self, filt, update, upsert=False):
        for d in self.docs:
            if self._match(d, filt):
                d.update(update.get("$set", {}))
                for key, val in update.get("$push", {}).items():
                    d.setdefault(key, []).append(val)
                return SimpleNamespace(matched_count=1, upserted_id=None)
        if upsert:
            new = dict(filt)
            new.update(update.get("$setOnInsert", {}))
            new.update(update.get("$set", {}))
            self.docs.append(new)
            return SimpleNamespace(matched_count=0, upserted_id="fake")
        return SimpleNamespace(matched_count=0, upserted_id=None)


class _FakeDB:
    def __init__(self):
        self.users = _FakeColl()
        self.profiles = _FakeColl()
        self.analysis_history = _FakeColl()
        self.forum_posts = _FakeColl()
        self.commands = []                       # records db.command(...) calls (ensure_schema)

    def command(self, command, value=None, **kwargs):
        self.commands.append((command, value, kwargs))
        return {"ok": 1}


@pytest.fixture
def db():
    return _FakeDB()


# ---- indexes + schema ----
def test_ensure_indexes_creates_unique_constraints(db_mod, db):
    db_mod.ensure_indexes(db)
    assert ("username", True) in db.users.indexes            # unique username
    assert ("id", True) in db.forum_posts.indexes            # unique forum post id
    assert ("username", True) in db.profiles.indexes         # one profile per user
    assert ("username", False) in db.analysis_history.indexes  # perf (non-unique) per-user history scan


def test_ensure_schema_applies_a_jsonschema_validator_to_every_collection(db_mod, db):
    db_mod.ensure_schema(db)
    targets = {value for (cmd, value, kw) in db.commands if cmd == "collMod"}
    assert targets == {"users", "profiles", "analysis_history", "forum_posts"}
    for (cmd, value, kw) in db.commands:
        assert "$jsonSchema" in kw["validator"]              # each carries a shape validator


# ---- users ----
def test_create_user_then_get(db_mod, db):
    assert db_mod.create_user(db, "alice", "hash123") is True
    rec = db_mod.get_user(db, "alice")
    assert rec["username"] == "alice"
    assert rec["password_hash"] == "hash123"
    assert "_id" not in rec  # never leak the raw mongo id


def test_create_duplicate_user_returns_false(db_mod, db):
    assert db_mod.create_user(db, "alice", "h1") is True
    assert db_mod.create_user(db, "alice", "h2") is False
    assert db_mod.get_user(db, "alice")["password_hash"] == "h1"  # original wins, no overwrite


def test_get_missing_user_is_none(db_mod, db):
    assert db_mod.get_user(db, "nobody") is None


# ---- profiles ----
def test_save_then_get_profile(db_mod, db):
    profile = {"age": 30, "goal": "maintain"}
    db_mod.save_profile(db, "alice", profile)
    assert db_mod.get_profile(db, "alice") == profile


def test_save_profile_overwrites(db_mod, db):
    db_mod.save_profile(db, "alice", {"age": 30})
    db_mod.save_profile(db, "alice", {"age": 31})
    assert db_mod.get_profile(db, "alice") == {"age": 31}


def test_get_missing_profile_is_none(db_mod, db):
    assert db_mod.get_profile(db, "alice") is None


# ---- history ----
def test_list_history_empty(db_mod, db):
    assert db_mod.list_history(db, "alice") == []


def test_list_history_returns_entries_for_user_only(db_mod, db):
    db.analysis_history.docs.append({"username": "alice", "entry": {"assessment": "Ready"}})
    db.analysis_history.docs.append({"username": "bob", "entry": {"assessment": "Rest"}})
    out = db_mod.list_history(db, "alice")
    assert out == [{"assessment": "Ready"}]


def test_add_history_then_list_roundtrip(db_mod, db):
    db_mod.add_history(db, "alice", {"assessment": "Ready", "timestamp": "t1"})
    db_mod.add_history(db, "alice", {"assessment": "Rest", "timestamp": "t2"})
    db_mod.add_history(db, "bob", {"assessment": "Go", "timestamp": "t3"})
    out = db_mod.list_history(db, "alice")
    assert out == [{"assessment": "Ready", "timestamp": "t1"}, {"assessment": "Rest", "timestamp": "t2"}]


# ---- forum ----
def test_forum_create_then_get_and_list(db_mod, db):
    post = db_mod.forum_create_post(db, "alice", "Title", "Body", False)
    assert post["id"] and isinstance(post["id"], str)
    assert post["score"] == 0 and post["comments"] == []
    assert "votes" not in post and "_id" not in post  # internal/raw fields not leaked
    assert db_mod.forum_get_post(db, post["id"])["body"] == "Body"
    assert len(db_mod.forum_list_posts(db)) == 1


def test_forum_get_missing_post_is_none(db_mod, db):
    assert db_mod.forum_get_post(db, "does-not-exist") is None


def test_forum_add_comment(db_mod, db):
    pid = db_mod.forum_create_post(db, "alice", "T", "B", False)["id"]
    comment = db_mod.forum_add_comment(db, pid, "bob", "nice")
    assert comment == {"author": "bob", "body": "nice"}
    assert db_mod.forum_get_post(db, pid)["comments"] == [{"author": "bob", "body": "nice"}]


def test_forum_add_comment_on_missing_post_is_none(db_mod, db):
    assert db_mod.forum_add_comment(db, "nope", "bob", "x") is None


def test_forum_vote_sets_and_replaces_score(db_mod, db):
    pid = db_mod.forum_create_post(db, "alice", "T", "B", False)["id"]
    assert db_mod.forum_vote(db, pid, "alice", 1) == 1
    assert db_mod.forum_vote(db, pid, "alice", -1) == -1  # one vote per user — replaces, not adds


def test_forum_votes_aggregate_across_users(db_mod, db):
    pid = db_mod.forum_create_post(db, "alice", "T", "B", False)["id"]
    db_mod.forum_vote(db, pid, "alice", 1)
    assert db_mod.forum_vote(db, pid, "bob", 1) == 2  # distinct users sum


def test_forum_vote_on_missing_post_is_none(db_mod, db):
    assert db_mod.forum_vote(db, "nope", "alice", 1) is None


def test_forum_update_post_by_author(db_mod, db):
    pid = db_mod.forum_create_post(db, "alice", "Old", "old body", False)["id"]
    out = db_mod.forum_update_post(db, pid, "alice", "New", "new body")
    assert out["title"] == "New" and out["body"] == "new body"
    assert db_mod.forum_get_post(db, pid)["title"] == "New"


def test_forum_update_post_by_non_author_is_forbidden(db_mod, db):
    pid = db_mod.forum_create_post(db, "alice", "T", "b", False)["id"]
    assert db_mod.forum_update_post(db, pid, "bob", "X", "y") == db_mod.FORBIDDEN
    assert db_mod.forum_get_post(db, pid)["title"] == "T"  # unchanged


def test_forum_update_missing_post_is_none(db_mod, db):
    assert db_mod.forum_update_post(db, "nope", "alice", "X", "y") is None


def test_forum_delete_post_by_author(db_mod, db):
    pid = db_mod.forum_create_post(db, "alice", "T", "b", False)["id"]
    assert db_mod.forum_delete_post(db, pid, "alice") is True
    assert db_mod.forum_get_post(db, pid) is None  # gone


def test_forum_delete_post_by_non_author_is_forbidden(db_mod, db):
    pid = db_mod.forum_create_post(db, "alice", "T", "b", False)["id"]
    assert db_mod.forum_delete_post(db, pid, "bob") == db_mod.FORBIDDEN
    assert db_mod.forum_get_post(db, pid) is not None  # still there


def test_forum_delete_missing_post_is_none(db_mod, db):
    assert db_mod.forum_delete_post(db, "nope", "alice") is None


def test_votes_are_stored_as_a_list_not_keyed_by_username(db_mod, db):
    # votes must be a list of {user, value} — NOT a dict keyed by username (usernames can contain
    # '.'/'$', which are illegal/fragile MongoDB field names). Catches a regression to the dict form.
    pid = db_mod.forum_create_post(db, "alice", "T", "B", False)["id"]
    db_mod.forum_vote(db, pid, "bob.smith", 1)
    raw = db.forum_posts.find_one({"id": pid})
    assert isinstance(raw["votes"], list)
    assert raw["votes"] == [{"user": "bob.smith", "value": 1}]


def test_forum_vote_handles_dotted_or_dollar_usernames(db_mod, db):
    pid = db_mod.forum_create_post(db, "alice", "T", "B", False)["id"]
    assert db_mod.forum_vote(db, pid, "bob.smith", 1) == 1
    assert db_mod.forum_vote(db, pid, "$admin", 1) == 2        # distinct users sum
    assert db_mod.forum_vote(db, pid, "bob.smith", -1) == 0    # same user replaces (1 -> -1)


# ---- robustness fixes (from the adversarial review) ----
def test_create_user_returns_false_on_duplicate_key_race(db_mod, db):
    # two registrations of the same username race; the loser's upsert hits the unique index and the
    # driver raises DuplicateKeyError — create_user must report that as False, not blow up.
    from pymongo.errors import DuplicateKeyError

    def _raise(*a, **k):
        raise DuplicateKeyError("E11000 duplicate key error: username")

    db.users.update_one = _raise
    assert db_mod.create_user(db, "alice", "h") is False


def test_get_user_missing_password_hash_is_treated_as_no_user(db_mod, db):
    db.users.docs.append({"username": "corrupt"})             # no password_hash (partial/corrupt write)
    assert db_mod.get_user(db, "corrupt") is None             # fails closed, no KeyError


def test_get_profile_with_no_profile_field_is_none(db_mod, db):
    db.profiles.docs.append({"username": "amy"})              # row exists but has no profile blob
    assert db_mod.get_profile(db, "amy") is None


def test_list_history_skips_rows_without_entry(db_mod, db):
    db.analysis_history.docs.append({"username": "alice", "entry": {"assessment": "Ready"}})
    db.analysis_history.docs.append({"username": "alice"})    # malformed: no entry -> skipped, not raised
    assert db_mod.list_history(db, "alice") == [{"assessment": "Ready"}]


def test_forum_vote_write_is_guarded_by_the_votes_cas_filter(db_mod, db):
    pid = db_mod.forum_create_post(db, "alice", "T", "b", False)["id"]
    captured = {}
    real_update = db.forum_posts.update_one

    def _spy(filt, update, **k):
        captured["filt"] = filt
        return real_update(filt, update, **k)

    db.forum_posts.update_one = _spy
    db_mod.forum_vote(db, pid, "bob", 1)
    assert captured["filt"]["votes"] == []                    # first vote is conditional on the prior (empty) array


def test_forum_vote_returns_none_if_post_deleted_during_cas(db_mod, db):
    pid = db_mod.forum_create_post(db, "alice", "T", "b", False)["id"]
    real_find, calls = db.forum_posts.find_one, {"n": 0}

    def _flaky_find(filt):
        calls["n"] += 1
        return real_find(filt) if calls["n"] == 1 else None   # "deleted" right after the first read

    db.forum_posts.find_one = _flaky_find
    db.forum_posts.update_one = lambda *a, **k: SimpleNamespace(matched_count=0)  # CAS miss
    assert db_mod.forum_vote(db, pid, "alice", 1) is None


def test_forum_vote_raises_after_exhausting_retries(db_mod, db):
    pid = db_mod.forum_create_post(db, "alice", "T", "b", False)["id"]
    db.forum_posts.update_one = lambda *a, **k: SimpleNamespace(matched_count=0)  # write never lands
    with pytest.raises(RuntimeError):
        db_mod.forum_vote(db, pid, "alice", 1)


def test_forum_update_post_returns_none_if_deleted_during_write(db_mod, db):
    pid = db_mod.forum_create_post(db, "alice", "T", "b", False)["id"]
    db.forum_posts.update_one = lambda *a, **k: SimpleNamespace(matched_count=0)  # post gone before write
    assert db_mod.forum_update_post(db, pid, "alice", "X", "y") is None
