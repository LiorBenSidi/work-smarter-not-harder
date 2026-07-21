"""Real-Mongo integration test for the cold-seed. OWNER: Lior.

Runs the ACTUAL ``db/seed.py`` against a real MongoDB — so it exercises the one path the fake unit test
can't: ``forum_vote``'s server-side aggregation-pipeline update, the real unique indexes, and the real
newest-first feed read after back-dating. **Skips cleanly** when no DB is reachable, so CI stays green
without one; it runs in CI against the ``mongo:7`` service on every PR.

Run against a throwaway database (note the trailing ``/dbname``):
    TEST_MONGO_URI="mongodb://localhost:27017/worksmarter_seed_test" \
        python -m pytest tests/Integration_Tests/test_seed_mongo.py -v
"""
import importlib.util
import os
from pathlib import Path

import pytest
from werkzeug.security import check_password_hash

ROOT = Path(__file__).resolve().parents[2]
_COLLECTIONS = ("users", "profiles", "analysis_history", "forum_posts",
                "forum_comments", "messages", "notifications", "meta")


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, str(ROOT / rel))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def db_mod():
    pytest.importorskip("pymongo")
    return _load("web_db_seed_test", "web/services/db.py")


@pytest.fixture
def seed_mod():
    pytest.importorskip("pymongo")
    return _load("seed_seed_test", "db/seed.py")


@pytest.fixture
def real_db():
    pytest.importorskip("pymongo")
    uri = os.environ.get("TEST_MONGO_URI")
    if not uri:
        pytest.skip("set TEST_MONGO_URI (with a /dbname) to run the real-Mongo cold-seed test")
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
    client = MongoClient(uri, serverSelectionTimeoutMS=1500)
    try:
        client.admin.command("ping")
    except PyMongoError:
        pytest.skip(f"no reachable MongoDB at {uri}")
    db = client.get_default_database()
    if db is None:
        pytest.skip("TEST_MONGO_URI must include a database name, e.g. .../worksmarter_seed_test")
    for name in _COLLECTIONS:
        db[name].drop()
    db_mod_local = _load("web_db_provision", "web/services/db.py")
    db_mod_local.ensure_indexes(db)          # the real unique indexes the seed relies on
    yield db
    for name in _COLLECTIONS:
        db[name].drop()
    client.close()


def test_seed_populates_clients_posts_comments_and_likes(seed_mod, db_mod, real_db):
    result = seed_mod.apply_seed(db_mod, real_db)

    assert result == {"users": len(seed_mod.SEED_USERS),
                      "posts": len(seed_mod.SEED_POSTS),
                      "comments": len(seed_mod.SEED_COMMENTS)}
    assert real_db.users.count_documents({}) == len(seed_mod.SEED_USERS)
    assert real_db.forum_posts.count_documents({}) == len(seed_mod.SEED_POSTS)
    assert real_db.forum_comments.count_documents({}) == len(seed_mod.SEED_COMMENTS)

    # the real pipeline forum_vote actually moved scores (the fake can't run it) — prove likes landed.
    liked = list(real_db.forum_posts.find({"score": {"$gt": 0}}))
    assert liked, "seeded likes must produce positive post scores via the real forum_vote pipeline"
    for post in liked:
        assert post["score"] == sum(v["value"] for v in post["votes"])  # score == sum of votes, per contract


def test_seeded_feed_reads_newest_first_after_backdating(seed_mod, db_mod, real_db):
    seed_mod.apply_seed(db_mod, real_db)
    # the real indexed, bounded feed read — the exact call the app serves.
    posts = db_mod.forum_list_posts(real_db)
    titles = [p["title"] for p in posts]
    assert titles[0] == seed_mod.SEED_POSTS[-1][1], "newest-backdated post must lead the feed"
    assert titles[-1] == seed_mod.SEED_POSTS[0][1], "oldest-backdated post must trail the feed"


def test_seeded_accounts_authenticate_against_real_mongo(seed_mod, db_mod, real_db):
    seed_mod.apply_seed(db_mod, real_db)
    for handle, _display, _email in seed_mod.SEED_USERS:
        doc = real_db.users.find_one({"username": handle})
        assert doc is not None and check_password_hash(doc["password_hash"], seed_mod.SEED_PASSWORD)


def test_seed_is_idempotent_against_real_mongo(seed_mod, db_mod, real_db):
    seed_mod.apply_seed(db_mod, real_db)
    posts_before = real_db.forum_posts.count_documents({})
    comments_before = real_db.forum_comments.count_documents({})
    users_before = real_db.users.count_documents({})

    second = seed_mod.apply_seed(db_mod, real_db)
    assert second == {"users": 0, "posts": 0, "comments": 0}
    assert real_db.forum_posts.count_documents({}) == posts_before
    assert real_db.forum_comments.count_documents({}) == comments_before
    assert real_db.users.count_documents({}) == users_before
