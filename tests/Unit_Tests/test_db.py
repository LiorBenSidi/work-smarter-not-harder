"""Unit tests for the thin core CRUD in web/services/db.py. OWNER: Lior (thin core CRUD).

The data layer is exercised against an in-memory fake collection (the course's mocking technique —
no real Mongo, no Docker), so these pin the *behaviour contract* the web stores depend on:
``get_user`` / ``create_user`` / ``get_profile`` / ``save_profile`` / ``list_history`` and the five
``forum_*`` functions. The fake implements only the pymongo operators db.py uses.
"""
import importlib.util
import re
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


class _FakeCursor:
    """Minimal pymongo-cursor stand-in: iterable + supports .limit(n). Records the applied limit on the
    parent collection so a test can assert a read was BOUNDED (not an unlimited scan)."""

    def __init__(self, rows, coll=None):
        self._rows = rows
        self._coll = coll

    def limit(self, n):
        if self._coll is not None:
            self._coll.last_limit = n
        return _FakeCursor(self._rows[:n] if n else self._rows, self._coll)

    def sort(self, field, direction=1):
        rows = sorted(self._rows, key=lambda d: d.get(field, 0), reverse=(direction < 0))
        return _FakeCursor(rows, self._coll)

    def __iter__(self):
        return iter(self._rows)


class _FakeColl:
    """Minimal stand-in for a pymongo collection — supports just the ops db.py calls."""

    def __init__(self):
        self.docs = []
        self.indexes = []
        self.last_limit = None      # the n from the most recent find(...).limit(n), for read-bound assertions

    def create_index(self, key, unique=False, **kwargs):   # **kwargs tolerates partialFilterExpression etc.
        self.indexes.append((key, unique))

    def _match(self, doc, filt):
        # AND every top-level key. `$or` is ANDed with its siblings (real Mongo semantics); `$exists` and
        # `$regex`/`$options` are the operators search_users relies on. Any other value = exact equality.
        for k, v in filt.items():
            if k == "$or":
                if not any(self._match(doc, sub) for sub in v):
                    return False
            elif isinstance(v, dict) and ("$exists" in v or "$regex" in v):
                val = doc.get(k)
                if "$exists" in v and (val is not None) != bool(v["$exists"]):
                    return False
                if "$regex" in v:
                    flags = re.IGNORECASE if "i" in v.get("$options", "") else 0
                    if val is None or re.search(v["$regex"], str(val), flags) is None:
                        return False
            elif doc.get(k) != v:
                return False
        return True

    def find_one(self, filt):
        return next((dict(d) for d in self.docs if self._match(d, filt)), None)

    def find(self, filt=None, projection=None):
        rows = [dict(d) for d in self.docs if self._match(d, filt or {})]
        if projection:                                        # honor a 1-projection (drop _id) like pymongo
            keep = [k for k, want in projection.items() if want and k != "_id"]
            rows = [{k: d[k] for k in keep if k in d} for d in rows]
        return _FakeCursor(rows, self)                        # cursor: iterable + chainable .limit()

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id="fake")

    def delete_one(self, filt):
        for i, d in enumerate(self.docs):
            if self._match(d, filt):
                del self.docs[i]
                return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    def delete_many(self, filt):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not self._match(d, filt)]
        return SimpleNamespace(deleted_count=before - len(self.docs))

    def update_one(self, filt, update, upsert=False):
        for d in self.docs:
            if self._match(d, filt):
                d.update(update.get("$set", {}))
                for key, val in update.get("$push", {}).items():
                    d.setdefault(key, []).append(val)
                for key, val in update.get("$inc", {}).items():   # forum_bump_rev's atomic counter
                    d[key] = d.get(key, 0) + val
                return SimpleNamespace(matched_count=1, upserted_id=None)
        if upsert:
            new = dict(filt)
            new.update(update.get("$setOnInsert", {}))
            new.update(update.get("$set", {}))
            for key, val in update.get("$inc", {}).items():       # first bump upserts {_id, v: <val>}
                new[key] = new.get(key, 0) + val
            self.docs.append(new)
            return SimpleNamespace(matched_count=0, upserted_id="fake")
        return SimpleNamespace(matched_count=0, upserted_id=None)

    def update_many(self, filt, update):
        n = 0
        for d in self.docs:
            if self._match(d, filt):
                d.update(update.get("$set", {}))
                n += 1
        return SimpleNamespace(matched_count=n)


class _FakeDB:
    def __init__(self):
        self.users = _FakeColl()
        self.profiles = _FakeColl()
        self.analysis_history = _FakeColl()
        self.forum_posts = _FakeColl()
        self.messages = _FakeColl()
        self.notifications = _FakeColl()
        self.meta = _FakeColl()                  # the forum_rev counter lives here (real-time push)
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
    assert ("email", True) in db.users.indexes               # unique email (partial) — one account per email
    assert ("id", True) in db.forum_posts.indexes            # unique forum post id
    assert ("username", True) in db.profiles.indexes         # one profile per user
    assert ("username", False) in db.analysis_history.indexes  # perf (non-unique) per-user history scan


def test_ensure_schema_applies_a_jsonschema_validator_to_every_collection(db_mod, db):
    db_mod.ensure_schema(db)
    targets = {value for (cmd, value, kw) in db.commands if cmd == "collMod"}
    assert targets == {"users", "profiles", "analysis_history", "forum_posts", "messages", "notifications"}
    for (cmd, value, kw) in db.commands:
        assert "$jsonSchema" in kw["validator"]              # each carries a shape validator


def test_ensure_schema_skips_when_collmod_is_unauthorized(db_mod):
    # a restricted user (no collMod rights) is skipped, not crashed, and never falls through to create (C1)
    from pymongo.errors import OperationFailure

    class _UnauthDB:
        def __init__(self):
            self.created = []

        def command(self, *a, **k):
            raise OperationFailure("not authorized", code=13)

        def create_collection(self, name, **k):
            self.created.append(name)

    db = _UnauthDB()
    db_mod.ensure_schema(db)                                  # must NOT raise
    assert db.created == []                                   # and must NOT create_collection on a 13


def test_ensure_schema_creates_collection_when_namespace_absent(db_mod):
    # NamespaceNotFound (code 26) -> create the collection WITH the validator (C1/C2 path)
    from pymongo.errors import OperationFailure

    class _AbsentDB:
        def __init__(self):
            self.created = []

        def command(self, *a, **k):
            raise OperationFailure("ns not found", code=26)

        def create_collection(self, name, **k):
            self.created.append(name)

    db = _AbsentDB()
    db_mod.ensure_schema(db)
    assert set(db.created) == {"users", "profiles", "analysis_history", "forum_posts", "messages", "notifications"}


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


# ---- users: directory search (DM picker) ----
def _seed_search_users(db_mod, db):
    db_mod.create_user(db, "coach_maya", "h", email="maya@x.io", display_name="Maya Coach")
    db_mod.create_user(db, "marco_r", "h", email="marco@x.io", display_name="Marco")
    db_mod.create_user(db, "dan", "h", email="dan@x.io", display_name="Daniela")


def test_search_users_matches_username_and_display_name(db_mod, db):
    _seed_search_users(db_mod, db)
    by_user = [r["username"] for r in db_mod.search_users(db, "mar")]      # username substring
    assert by_user == ["marco_r"]
    by_disp = [r["username"] for r in db_mod.search_users(db, "daniela")]  # display-name substring
    assert by_disp == ["dan"]


def test_search_users_excludes_the_caller(db_mod, db):
    _seed_search_users(db_mod, db)
    names = [r["username"] for r in db_mod.search_users(db, "ma", exclude="coach_maya")]
    assert "coach_maya" not in names and "marco_r" in names


def test_search_users_requires_two_chars(db_mod, db):
    _seed_search_users(db_mod, db)
    assert db_mod.search_users(db, "m") == []
    assert db_mod.search_users(db, "") == []
    assert db_mod.search_users(db, " ") == []


def test_search_users_returns_only_public_fields(db_mod, db):
    _seed_search_users(db_mod, db)
    for r in db_mod.search_users(db, "ma"):
        assert set(r) == {"username", "display_name"}   # never password_hash / email / _id
        assert "email" not in r and "password_hash" not in r


def test_search_users_treats_regex_metacharacters_literally(db_mod, db):
    _seed_search_users(db_mod, db)
    assert db_mod.search_users(db, ".*") == []            # ".*" is a literal search, NOT match-everything
    db_mod.create_user(db, "weird.*name", "h", display_name="Odd")
    assert [r["username"] for r in db_mod.search_users(db, ".*name")] == ["weird.*name"]


def test_search_users_caps_result_count(db_mod, db):
    for i in range(20):
        db_mod.create_user(db, f"runner{i:02d}", "h", display_name=f"Runner {i:02d}")
    assert len(db_mod.search_users(db, "runner", limit=8)) == 8


def test_search_users_ranks_prefix_matches_first(db_mod, db):
    db_mod.create_user(db, "xander", "h", display_name="has an in the middle")  # 'an' mid-substring
    db_mod.create_user(db, "ana", "h", display_name="Ana")                      # 'an' prefix
    names = [r["username"] for r in db_mod.search_users(db, "an")]
    assert names[0] == "ana"                              # prefix ranked ahead of the mid-string match


def test_search_users_ignores_accounts_without_password_hash(db_mod, db):
    db_mod.create_user(db, "realuser", "h", display_name="Real")
    db.users.docs.append({"username": "ghostuser", "display_name": "Ghost"})   # partial/corrupt: no hash
    names = [r["username"] for r in db_mod.search_users(db, "user")]
    assert names == ["realuser"]


def test_search_users_bounds_the_db_read(db_mod, db):
    # HIGH-fix regression: an unanchored $regex is a collection scan, so search_users must .limit() the cursor
    # rather than pull every match into memory before capping. With 50 matches the caller still gets <=8 AND
    # the DB read was bounded (last_limit set + small). Without the .limit(), last_limit stays None -> fails.
    for i in range(50):
        db_mod.create_user(db, f"runner{i:02d}", "h", display_name=f"Runner {i:02d}")
    results = db_mod.search_users(db, "runner", limit=8)
    assert len(results) == 8
    assert db.users.last_limit is not None and db.users.last_limit <= 8 * 4


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
# NOTE: forum_vote / forum_vote_comment now use an atomic aggregation-pipeline update (find_one_and_update
# with a [$set ...] pipeline) that eliminated the old CAS-retry livelock. The in-memory fake can't execute a
# pipeline, so their behaviour (set / replace / aggregate / unknown -> None / list-storage / '.'/'$'
# usernames) AND concurrency-safety are pinned against REAL Mongo in
# tests/Integration_Tests/test_db_mongo.py (which runs in CI with a mongo:7 service). Everything else in the
# thin CRUD stays fake-tested here.
def _seed_vote(db, post_id, user, value):
    """Seed a vote straight into the fake post doc — so purge/export tests that just need pre-existing vote
    data don't have to go through forum_vote (which is now real-Mongo-only, per the note above)."""
    for d in db.forum_posts.docs:
        if d.get("id") == post_id:
            d.setdefault("votes", []).append({"user": user, "value": value})
            d["score"] = sum(v["value"] for v in d["votes"])
            return


def test_forum_create_then_get_and_list(db_mod, db):
    post = db_mod.forum_create_post(db, "alice", "Title", "Body", False)
    assert post["id"] and isinstance(post["id"], str)
    assert post["score"] == 0 and post["comments"] == []
    assert "votes" not in post and "_id" not in post  # internal/raw fields not leaked
    assert db_mod.forum_get_post(db, post["id"])["body"] == "Body"
    assert len(db_mod.forum_list_posts(db)) == 1


def test_forum_post_carries_a_created_at_timestamp(db_mod, db):
    # The forum orders newest-first by default + shows each post's age, so every post must carry a positive
    # created_at that survives get + list (it's the field the client sorts on and renders).
    post = db_mod.forum_create_post(db, "alice", "T", "B", False)
    assert isinstance(post["created_at"], (int, float)) and post["created_at"] > 0
    assert db_mod.forum_get_post(db, post["id"])["created_at"] == post["created_at"]
    assert db_mod.forum_list_posts(db)[0]["created_at"] == post["created_at"]


def test_shape_backfills_created_at_from_the_object_id(db_mod):
    # A post created BEFORE the created_at field existed has none -> it must still get a real, positive
    # created_at (derived from the Mongo _id's embedded insertion time), else the sort/direction toggle is a
    # no-op on old posts and the age doesn't render. Regression for the "↓ Newest / ↑ Oldest does nothing" bug.
    from bson import ObjectId
    oid = ObjectId()
    shaped = db_mod._shape({"_id": oid, "id": "p1", "author": "a", "title": "t", "body": "b"})   # no created_at
    assert shaped["created_at"] == oid.generation_time.timestamp() and shaped["created_at"] > 0
    # an explicit created_at always wins over the _id fallback
    assert db_mod._shape({"_id": oid, "id": "p2", "author": "a", "title": "t", "body": "b", "created_at": 123.5})["created_at"] == 123.5


def test_forum_get_missing_post_is_none(db_mod, db):
    assert db_mod.forum_get_post(db, "does-not-exist") is None


def test_forum_add_comment(db_mod, db):
    pid = db_mod.forum_create_post(db, "alice", "T", "B", False)["id"]
    comment = db_mod.forum_add_comment(db, pid, "bob", "nice")
    assert comment["author"] == "bob" and comment["body"] == "nice" and comment["score"] == 0
    assert comment["id"] and isinstance(comment["id"], str) and "votes" not in comment
    stored = db_mod.forum_get_post(db, pid)["comments"]
    assert len(stored) == 1 and stored[0]["id"] == comment["id"]
    assert stored[0]["author"] == "bob" and stored[0]["body"] == "nice" and stored[0]["score"] == 0
    assert "votes" not in stored[0]                      # internal tally not leaked to the public shape


def test_forum_add_comment_on_missing_post_is_none(db_mod, db):
    assert db_mod.forum_add_comment(db, "nope", "bob", "x") is None


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


def test_forum_rev_starts_at_zero_and_every_mutation_bumps_it(db_mod, db):
    # Real-time push contract: the SSE stream watches forum_get_rev; each MUTATION must advance it so open
    # clients re-fetch. (vote / vote_comment run a Mongo pipeline the fake can't execute — their bump is
    # pinned against real Mongo in test_db_mongo.py. Here: create / comment / update / delete.)
    assert db_mod.forum_get_rev(db) == 0                       # nothing happened yet
    pid = db_mod.forum_create_post(db, "alice", "T", "B", False)["id"]
    assert db_mod.forum_get_rev(db) == 1                       # a new post is a change
    db_mod.forum_add_comment(db, pid, "bob", "nice")
    assert db_mod.forum_get_rev(db) == 2                       # a comment is a change
    db_mod.forum_update_post(db, pid, "alice", "T2", "B2")
    assert db_mod.forum_get_rev(db) == 3                       # an edit is a change
    db_mod.forum_delete_post(db, pid, "alice")
    assert db_mod.forum_get_rev(db) == 4                       # a delete is a change


def test_forum_rev_does_not_move_on_a_no_op_mutation(db_mod, db):
    # A rejected mutation is NOT a change — an unknown post or a non-author edit/delete must leave the rev
    # untouched, so the stream doesn't ping every client for a write that never landed.
    pid = db_mod.forum_create_post(db, "alice", "T", "B", False)["id"]
    rev = db_mod.forum_get_rev(db)
    assert db_mod.forum_add_comment(db, "nope", "bob", "x") is None
    assert db_mod.forum_update_post(db, pid, "mallory", "X", "y") == db_mod.FORBIDDEN
    assert db_mod.forum_delete_post(db, pid, "mallory") == db_mod.FORBIDDEN
    assert db_mod.forum_get_rev(db) == rev                     # no successful write -> no bump


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


def test_update_display_name_changes_only_the_shown_name(db_mod, db):
    db_mod.create_user(db, "alice", "h1", "alice@ex.com", display_name="Alice")
    assert db_mod.update_display_name(db, "alice", "Alice B.") is True
    u = db_mod.get_user(db, "alice")
    assert u["display_name"] == "Alice B."                    # shown name updated
    assert u["username"] == "alice" and u["password_hash"] == "h1"   # handle + credential untouched
    assert db_mod.update_display_name(db, "ghost", "X") is False     # unknown handle -> False


# ---- account deletion (GDPR erasure) ----
def test_delete_user_profile_and_history(db_mod, db):
    db_mod.create_user(db, "alice", "h1")
    db_mod.save_profile(db, "alice", {"age": 30})
    db_mod.add_history(db, "alice", {"x": 1})
    assert db_mod.delete_user(db, "alice") is True
    assert db_mod.get_user(db, "alice") is None
    db_mod.delete_profile(db, "alice")
    assert db_mod.get_profile(db, "alice") is None
    db_mod.delete_history(db, "alice")
    assert db_mod.list_history(db, "alice") == []
    assert db_mod.delete_user(db, "ghost") is False              # nothing to delete -> False


def test_forum_purge_user_strips_authored_and_voted_content(db_mod, db):
    pa = db_mod.forum_create_post(db, "alice", "A", "a", False)["id"]
    pb = db_mod.forum_create_post(db, "bob", "B", "b", False)["id"]
    db_mod.forum_add_comment(db, pb, "alice", "hi")
    _seed_vote(db, pb, "alice", 1)          # seed votes directly: forum_vote itself is now real-Mongo-only
    _seed_vote(db, pb, "bob", 1)
    db_mod.forum_purge_user(db, "alice")
    assert db_mod.forum_get_post(db, pa) is None                 # alice's own post gone
    post = db_mod.forum_get_post(db, pb)
    assert post is not None and post["score"] == 1               # her vote stripped, bob's kept
    assert all(c["author"] != "alice" for c in post["comments"]) # her comment stripped


def test_message_and_notification_delete_for_user(db_mod, db):
    db_mod.message_send(db, "alice", "bob", "hi")
    db_mod.message_send(db, "bob", "alice", "yo")
    db_mod.message_send(db, "bob", "carol", "unrelated")
    db_mod.notification_add(db, "alice", "dm", "bob", None, "x")
    db_mod.notification_add(db, "bob", "vote", "alice", None, "y")   # alice as actor
    db_mod.notification_add(db, "carol", "dm", "bob", None, "z")
    db_mod.message_delete_for_user(db, "alice")
    db_mod.notification_delete_for_user(db, "alice")
    assert db_mod.message_list_conversation(db, "alice", "bob") == []
    assert len(db_mod.message_list_conversation(db, "bob", "carol")) == 1   # unrelated survives
    assert db_mod.notification_list(db, "alice") == []
    assert db_mod.notification_list(db, "bob") == []                        # actor=alice removed
    assert len(db_mod.notification_list(db, "carol")) == 1                  # unrelated survives


# ---- email consent + data export (GDPR) ----
def test_email_consent_get_set(db_mod, db):
    db_mod.create_user(db, "alice", "h1")
    assert db_mod.get_email_consent(db, "alice") is False                # default (opt-in)
    assert db_mod.set_email_consent(db, "alice", True) is True
    assert db_mod.get_email_consent(db, "alice") is True
    assert db_mod.set_email_consent(db, "alice", False) is True
    assert db_mod.get_email_consent(db, "alice") is False
    assert db_mod.get_email_consent(db, "ghost") is False                # unknown handle -> False
    assert db_mod.set_email_consent(db, "ghost", True) is False


def test_forum_export_user(db_mod, db):
    db_mod.forum_create_post(db, "alice", "A", "a", False)
    bp = db_mod.forum_create_post(db, "bob", "B", "b", False)["id"]
    db_mod.forum_add_comment(db, bp, "alice", "hi")
    _seed_vote(db, bp, "alice", 1)          # seed the vote directly (forum_vote is now real-Mongo-only)
    out = db_mod.forum_export_user(db, "alice")
    assert [p["title"] for p in out["posts"]] == ["A"]                   # own post only
    assert [c["body"] for c in out["comments"]] == ["hi"]               # her comment on bob's post
    assert len(out["votes"]) == 1 and out["votes"][0]["post_id"] == bp   # her post vote


def test_message_export_for_user(db_mod, db):
    db_mod.message_send(db, "alice", "bob", "hi")
    db_mod.message_send(db, "bob", "alice", "yo")
    db_mod.message_send(db, "bob", "carol", "unrelated")
    out = db_mod.message_export_for_user(db, "alice")
    assert [m["body"] for m in out] == ["hi", "yo"]                     # both directions, not carol's


def test_get_profile_with_no_profile_field_is_none(db_mod, db):
    db.profiles.docs.append({"username": "amy"})              # row exists but has no profile blob
    assert db_mod.get_profile(db, "amy") is None


def test_list_history_skips_rows_without_entry(db_mod, db):
    db.analysis_history.docs.append({"username": "alice", "entry": {"assessment": "Ready"}})
    db.analysis_history.docs.append({"username": "alice"})    # malformed: no entry -> skipped, not raised
    assert db_mod.list_history(db, "alice") == [{"assessment": "Ready"}]


def test_forum_update_post_returns_none_if_deleted_during_write(db_mod, db):
    pid = db_mod.forum_create_post(db, "alice", "T", "b", False)["id"]
    db.forum_posts.update_one = lambda *a, **k: SimpleNamespace(matched_count=0)  # post gone before write
    assert db_mod.forum_update_post(db, pid, "alice", "X", "y") is None
