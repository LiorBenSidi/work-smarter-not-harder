"""Real-Mongo integration tests for the data layer. OWNER: Lior (thin CRUD).

The other db tests use an in-memory fake collection; these exercise the SAME functions against a real
MongoDB to catch pymongo-specific behaviour the fake can't (upsert results, _id handling, real index
enforcement, illegal field names). They **skip cleanly** when no DB is reachable, so CI stays green
without one.

Run against a throwaway database (note the trailing ``/dbname``):
    TEST_MONGO_URI="mongodb://localhost:27017/worksmarter_test" \
        python -m pytest tests/Integration_Tests/test_db_mongo.py -v
"""
import importlib.util
import os
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"
_COLLECTIONS = ("users", "profiles", "analysis_history", "forum_posts", "messages", "notifications")


@pytest.fixture
def db_mod():
    pytest.importorskip("pymongo")
    spec = importlib.util.spec_from_file_location("web_db_real", str(WEB / "services" / "db.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def real_db():
    pytest.importorskip("pymongo")
    uri = os.environ.get("TEST_MONGO_URI")
    if not uri:
        pytest.skip("set TEST_MONGO_URI (with a /dbname) to run real-Mongo integration tests")
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
    client = MongoClient(uri, serverSelectionTimeoutMS=1500)
    try:
        client.admin.command("ping")
    except PyMongoError:
        pytest.skip(f"no reachable MongoDB at {uri}")
    db = client.get_default_database()
    if db is None:
        pytest.skip("TEST_MONGO_URI must include a database name, e.g. .../worksmarter_test")
    for name in _COLLECTIONS:
        db[name].drop()                       # clean slate
    yield db
    for name in _COLLECTIONS:
        db[name].drop()                       # teardown
    client.close()


def test_users_roundtrip_and_dedupe(db_mod, real_db):
    db_mod.ensure_indexes(real_db)
    assert db_mod.create_user(real_db, "alice", "h1") is True
    assert db_mod.create_user(real_db, "alice", "h2") is False           # upsert dup -> False
    assert db_mod.get_user(real_db, "alice") == {"username": "alice", "password_hash": "h1", "email": None, "display_name": "alice"}  # no _id


def test_create_user_stores_and_returns_the_display_name(db_mod, real_db):
    # the identity model: the handle is unique; the display name is stored separately (need not be unique)
    # and comes back on get_user. A second account may share the display name under a different handle.
    db_mod.ensure_indexes(real_db)
    assert db_mod.create_user(real_db, "alex", "h1", "alex@example.com", display_name="Alex") is True
    assert db_mod.create_user(real_db, "alex-2", "h2", "alex2@example.com", display_name="Alex") is True
    u1 = db_mod.get_user(real_db, "alex")
    u2 = db_mod.get_user(real_db, "alex-2")
    assert u1["display_name"] == "Alex" == u2["display_name"]     # same shown name
    assert u1["username"] == "alex" and u2["username"] == "alex-2"  # distinct handles


def test_update_display_name_changes_the_shown_name_only(db_mod, real_db):
    # renaming updates display_name and leaves the handle (and everything keyed on it) + credential intact.
    db_mod.create_user(real_db, "alice", "h1", "alice@example.com", display_name="Alice")
    assert db_mod.update_display_name(real_db, "alice", "Alice B.") is True
    u = db_mod.get_user(real_db, "alice")
    assert u == {"username": "alice", "password_hash": "h1", "email": "alice@example.com", "display_name": "Alice B."}
    assert db_mod.update_display_name(real_db, "ghost", "Nobody") is False   # unknown handle -> False


def test_otp_challenge_roundtrip(db_mod, real_db):
    # the login-OTP seam against real Mongo: set -> get -> atomic $inc -> $unset, and clearing the
    # transient fields must leave the core identity doc untouched.
    db_mod.create_user(real_db, "alice", "h1")
    assert db_mod.get_otp(real_db, "alice") is None
    assert db_mod.set_otp(real_db, "alice", "otp-hash", 9999999999) is True
    assert db_mod.get_otp(real_db, "alice") == {"otp_hash": "otp-hash", "expires_at": 9999999999, "attempts": 0}
    assert db_mod.bump_otp_attempts(real_db, "alice") == 1
    assert db_mod.bump_otp_attempts(real_db, "alice") == 2
    db_mod.clear_otp(real_db, "alice")
    assert db_mod.get_otp(real_db, "alice") is None
    assert db_mod.get_user(real_db, "alice") == {"username": "alice", "password_hash": "h1", "email": None, "display_name": "alice"}


def test_profile_and_history_roundtrip(db_mod, real_db):
    db_mod.save_profile(real_db, "alice", {"age": 30, "goal": "maintain"})
    assert db_mod.get_profile(real_db, "alice") == {"age": 30, "goal": "maintain"}
    assert db_mod.list_history(real_db, "alice") == []


def test_forum_crud_and_problematic_username_vote(db_mod, real_db):
    pid = db_mod.forum_create_post(real_db, "alice", "T", "B", False)["id"]
    assert db_mod.forum_get_post(real_db, pid)["body"] == "B"
    cid = db_mod.forum_add_comment(real_db, pid, "bob", "nice")["id"]
    stored = db_mod.forum_get_post(real_db, pid)["comments"]
    assert len(stored) == 1 and stored[0]["author"] == "bob" and stored[0]["body"] == "nice"
    assert stored[0]["score"] == 0 and "votes" not in stored[0]        # internal tally not leaked
    # the votes-as-list fix: '.'/'$' usernames must be safe real-Mongo writes (would fail as field names)
    assert db_mod.forum_vote(real_db, pid, "bob.smith", 1) == 1
    assert db_mod.forum_vote(real_db, pid, "$admin", 1) == 2
    # comment votes use the same list-based tally, guarded by a nested-array CAS
    assert db_mod.forum_vote_comment(real_db, pid, cid, "bob.smith", 1) == 1
    assert db_mod.forum_vote_comment(real_db, pid, cid, "$admin", 1) == 2   # distinct users sum
    assert db_mod.forum_vote_comment(real_db, pid, cid, "bob.smith", -1) == 0  # same user replaces


def test_unique_index_is_actually_enforced(db_mod, real_db):
    from pymongo.errors import DuplicateKeyError
    db_mod.ensure_indexes(real_db)
    real_db.users.insert_one({"username": "alice", "password_hash": "x"})
    with pytest.raises(DuplicateKeyError):
        real_db.users.insert_one({"username": "alice", "password_hash": "y"})  # unique index blocks it


def test_perf_indexes_and_schema_validator_are_applied(db_mod, real_db):
    from pymongo.errors import WriteError
    db_mod.ensure_indexes(real_db)
    db_mod.ensure_schema(real_db)
    # the performance index exists on analysis_history.username
    assert any("username" in idx["key"] for idx in real_db.analysis_history.list_indexes())
    # the $jsonSchema validator rejects a structurally-wrong document (DB-layer defense)
    with pytest.raises(WriteError):
        real_db.users.insert_one({"username": "nopass"})        # missing required password_hash


def test_seed_is_idempotent(db_mod, real_db):
    import importlib.util

    seed_path = Path(__file__).resolve().parents[2] / "db" / "seed.py"
    spec = importlib.util.spec_from_file_location("seed_under_test", str(seed_path))
    seed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seed)
    uri = os.environ["TEST_MONGO_URI"]
    first = seed.seed(uri)                                       # empty forum -> seeds
    second = seed.seed(uri)                                      # already seeded -> no-op
    assert first == len(seed.SEED_POSTS) and second == 0
    assert real_db.forum_posts.count_documents({}) == len(seed.SEED_POSTS)
