"""Unit tests for the cold-seed (rubric §7 — fake clients + posts + comments). OWNER: Lior.

The seed is exercised two ways:
- here, against an in-memory fake db (the course's mocking technique), so the orchestration —
  who gets created, idempotency, the backdated timeline, login-ability — runs on any machine with no
  Mongo; the one op the fake can't do (``forum_vote``'s server-side aggregation-pipeline update) is
  monkeypatched to an equivalent read-modify-write (the real pipeline is covered by ``test_db`` and by
  ``tests/Integration_Tests/test_seed_mongo.py`` against a live mongo:7).
"""
import importlib.util
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from werkzeug.security import check_password_hash

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def db_mod():
    spec = importlib.util.spec_from_file_location("web_db_under_test", str(ROOT / "web" / "services" / "db.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def seed_mod():
    spec = importlib.util.spec_from_file_location("seed_under_test", str(ROOT / "db" / "seed.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Coll:
    """The handful of pymongo ops the seed's CRUD path actually calls."""

    def __init__(self):
        self.docs = []

    def create_index(self, *a, **k):
        pass

    def _match(self, doc, filt):
        return all(doc.get(k) == v for k, v in filt.items())

    def find_one(self, filt):
        return next((dict(d) for d in self.docs if self._match(d, filt)), None)

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id="x")

    def count_documents(self, filt, limit=0):
        n = sum(1 for d in self.docs if self._match(d, filt))
        return min(n, limit) if limit else n

    def update_one(self, filt, update, upsert=False):
        for d in self.docs:
            if self._match(d, filt):
                d.update(update.get("$set", {}))
                for k, v in update.get("$inc", {}).items():
                    d[k] = d.get(k, 0) + v
                return SimpleNamespace(matched_count=1, upserted_id=None)
        if upsert:
            new = dict(filt)
            new.update(update.get("$setOnInsert", {}))
            new.update(update.get("$set", {}))
            for k, v in update.get("$inc", {}).items():
                new[k] = new.get(k, 0) + v
            self.docs.append(new)
            return SimpleNamespace(matched_count=0, upserted_id="x")
        return SimpleNamespace(matched_count=0, upserted_id=None)


class _DB:
    def __init__(self):
        for name in ("users", "profiles", "analysis_history", "forum_posts",
                     "forum_comments", "messages", "notifications", "meta"):
            setattr(self, name, _Coll())


@pytest.fixture
def db():
    return _DB()


def _patch_post_vote(monkeypatch, db_mod):
    """forum_vote uses a server-side pipeline update the fake can't run — swap in an equivalent RMW."""
    def _vote(db, post_id, username, value):
        post = db.forum_posts.find_one({"id": post_id})
        if post is None:
            return None
        votes = [v for v in (post.get("votes") or []) if v.get("user") != username]
        votes.append({"user": username, "value": value})
        score = sum(v["value"] for v in votes)
        db.forum_posts.update_one({"id": post_id}, {"$set": {"votes": votes, "score": score}})
        return score
    monkeypatch.setattr(db_mod, "forum_vote", _vote)


# --------------------------------------------------------------- data integrity (no db)

def test_seed_data_is_internally_consistent(seed_mod):
    handles = {h for h, _, _ in seed_mod.SEED_USERS}
    assert len(handles) == len(seed_mod.SEED_USERS), "fake-client handles must be unique"
    emails = [e for _, _, e in seed_mod.SEED_USERS]
    assert len(set(emails)) == len(emails), "fake-client emails must be unique (one account per email)"

    n_posts = len(seed_mod.SEED_POSTS)
    for author, _title, _body, age in seed_mod.SEED_POSTS:
        assert author in handles, f"post author {author!r} is not a seeded client"
        assert age >= 0
    for post_index, author, _body, age in seed_mod.SEED_COMMENTS:
        assert 0 <= post_index < n_posts, "a comment references a post index that doesn't exist"
        assert author in handles, f"comment author {author!r} is not a seeded client"
        assert age < seed_mod.SEED_POSTS[post_index][3], "a comment can't predate the post it's on"
    for post_index, voter in seed_mod.SEED_POST_VOTES:
        assert 0 <= post_index < n_posts and voter in handles
    for comment_index, voter in seed_mod.SEED_COMMENT_VOTES:
        assert 0 <= comment_index < len(seed_mod.SEED_COMMENTS) and voter in handles


def test_seed_meets_the_rubric_minimums(seed_mod):
    # rubric §7: "a few fake clients, with a few posts and comments".
    assert len(seed_mod.SEED_USERS) >= 2
    assert len(seed_mod.SEED_POSTS) >= 2
    assert len(seed_mod.SEED_COMMENTS) >= 2


# --------------------------------------------------------------- behaviour (fake db)

def test_apply_seed_creates_the_fake_clients_posts_and_comments(seed_mod, db_mod, db, monkeypatch):
    _patch_post_vote(monkeypatch, db_mod)
    result = seed_mod.apply_seed(db_mod, db)

    assert result == {"users": len(seed_mod.SEED_USERS),
                      "posts": len(seed_mod.SEED_POSTS),
                      "comments": len(seed_mod.SEED_COMMENTS)}
    assert len(db.users.docs) == len(seed_mod.SEED_USERS)
    assert len(db.forum_posts.docs) == len(seed_mod.SEED_POSTS)
    assert len(db.forum_comments.docs) == len(seed_mod.SEED_COMMENTS)


def test_each_post_carries_its_real_comment_count(seed_mod, db_mod, db, monkeypatch):
    _patch_post_vote(monkeypatch, db_mod)
    seed_mod.apply_seed(db_mod, db)
    expected = {}
    for post_index, *_ in seed_mod.SEED_COMMENTS:
        expected[post_index] = expected.get(post_index, 0) + 1
    posts_in_order = db.forum_posts.docs  # insertion order == SEED_POSTS order
    for i, post in enumerate(posts_in_order):
        assert post["comment_count"] == expected.get(i, 0)


def test_likes_land_as_positive_scores(seed_mod, db_mod, db, monkeypatch):
    _patch_post_vote(monkeypatch, db_mod)
    seed_mod.apply_seed(db_mod, db)
    scored = [p for p in db.forum_posts.docs if p["score"] > 0]
    assert scored, "at least some seeded posts should carry likes so the forum isn't a flat zero-score wall"
    for post_index, _voter in seed_mod.SEED_POST_VOTES[:1]:
        votes = len([v for v in seed_mod.SEED_POST_VOTES if v[0] == post_index])
        assert db.forum_posts.docs[post_index]["score"] == votes  # each seed vote is +1, distinct voters


def test_content_is_backdated_onto_a_recent_timeline(seed_mod, db_mod, db, monkeypatch):
    _patch_post_vote(monkeypatch, db_mod)
    now = time.time()
    seed_mod.apply_seed(db_mod, db)
    created = [p["created_at"] for p in db.forum_posts.docs]
    assert all(ts < now for ts in created), "every seeded post must be backdated, not stamped 'now'"
    assert len(set(created)) == len(created), "posts should spread across distinct times, not pile on one instant"
    # oldest seeded post is ~14 days back; nothing should be in the future.
    assert min(created) <= now - 10 * seed_mod.DAY


def test_seeded_accounts_can_actually_log_in(seed_mod, db_mod, db, monkeypatch):
    # a 'fake client' is only useful if it's a real account: its stored hash must verify the seed password.
    _patch_post_vote(monkeypatch, db_mod)
    seed_mod.apply_seed(db_mod, db)
    a_user = db.users.find_one({"username": "coach_maya"})
    assert a_user is not None
    assert check_password_hash(a_user["password_hash"], seed_mod.SEED_PASSWORD)


def test_apply_seed_is_idempotent(seed_mod, db_mod, db, monkeypatch):
    _patch_post_vote(monkeypatch, db_mod)
    first = seed_mod.apply_seed(db_mod, db)
    users_after_first = len(db.users.docs)
    posts_after_first = len(db.forum_posts.docs)
    comments_after_first = len(db.forum_comments.docs)

    second = seed_mod.apply_seed(db_mod, db)
    # a re-run creates NOTHING new: users already exist, the forum is no longer empty.
    assert second == {"users": 0, "posts": 0, "comments": 0}
    assert len(db.users.docs) == users_after_first
    assert len(db.forum_posts.docs) == posts_after_first
    assert len(db.forum_comments.docs) == comments_after_first
    assert first["posts"] == posts_after_first  # sanity: the first run is what populated it
