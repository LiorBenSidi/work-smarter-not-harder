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
_COLLECTIONS = ("users", "profiles", "analysis_history", "forum_posts")


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
    assert db_mod.get_user(real_db, "alice") == {"username": "alice", "password_hash": "h1"}  # no _id


def test_profile_and_history_roundtrip(db_mod, real_db):
    db_mod.save_profile(real_db, "alice", {"age": 30, "goal": "maintain"})
    assert db_mod.get_profile(real_db, "alice") == {"age": 30, "goal": "maintain"}
    assert db_mod.list_history(real_db, "alice") == []


def test_forum_crud_and_problematic_username_vote(db_mod, real_db):
    pid = db_mod.forum_create_post(real_db, "alice", "T", "B", False)["id"]
    assert db_mod.forum_get_post(real_db, pid)["body"] == "B"
    db_mod.forum_add_comment(real_db, pid, "bob", "nice")
    assert db_mod.forum_get_post(real_db, pid)["comments"] == [{"author": "bob", "body": "nice"}]
    # the votes-as-list fix: '.'/'$' usernames must be safe real-Mongo writes (would fail as field names)
    assert db_mod.forum_vote(real_db, pid, "bob.smith", 1) == 1
    assert db_mod.forum_vote(real_db, pid, "$admin", 1) == 2


def test_unique_index_is_actually_enforced(db_mod, real_db):
    from pymongo.errors import DuplicateKeyError
    db_mod.ensure_indexes(real_db)
    real_db.users.insert_one({"username": "alice", "password_hash": "x"})
    with pytest.raises(DuplicateKeyError):
        real_db.users.insert_one({"username": "alice", "password_hash": "y"})  # unique index blocks it
