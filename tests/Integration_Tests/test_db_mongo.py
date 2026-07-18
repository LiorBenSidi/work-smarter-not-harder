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
_COLLECTIONS = ("users", "profiles", "analysis_history", "forum_posts", "forum_comments", "messages", "notifications")


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


def test_email_is_unique_across_handles(db_mod, real_db):
    # One email = one account (login identity): a DIFFERENT handle claiming an already-registered email is
    # rejected by the partial-unique users.email index -> create_user raises DuplicateEmailError (so the
    # route 409s once instead of the handle loop hammering every suffix against the same taken email).
    db_mod.ensure_indexes(real_db)
    assert db_mod.create_user(real_db, "alex", "h1", "x@e.com") is True
    with pytest.raises(db_mod.DuplicateEmailError):
        db_mod.create_user(real_db, "alex-2", "h2", "x@e.com")           # same email, new handle -> rejected
    assert db_mod.create_user(real_db, "dana", "h3", "y@e.com") is True  # a different email is fine
    # PARTIAL filter: multiple emailless accounts don't collide on a "missing" email
    assert db_mod.create_user(real_db, "noemail1", "h4") is True
    assert db_mod.create_user(real_db, "noemail2", "h5") is True
    # a duplicate HANDLE is still the plain False contract (not the email path)
    assert db_mod.create_user(real_db, "alex", "h9", "z@e.com") is False


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


def test_account_deletion_cascade_erases_all_user_data(db_mod, real_db):
    # the full GDPR erasure against real Mongo: every collection + the forum-consistency recompute.
    db_mod.ensure_indexes(real_db)
    db_mod.create_user(real_db, "alice", "h1", "a@ex.com", display_name="Alice")
    db_mod.save_profile(real_db, "alice", {"age": 30})
    db_mod.add_history(real_db, "alice", {"assessment": "Ready"})
    pa = db_mod.forum_create_post(real_db, "alice", "A", "a", False)["id"]
    pb = db_mod.forum_create_post(real_db, "bob", "B", "b", False)["id"]
    db_mod.forum_add_comment(real_db, pb, "alice", "hi")
    db_mod.forum_vote(real_db, pb, "alice", 1)
    db_mod.forum_vote(real_db, pb, "bob", 1)
    db_mod.message_send(real_db, "alice", "bob", "hey")
    db_mod.notification_add(real_db, "bob", "vote", "alice", None, "alice upvoted")
    # erase (route order: dependent data first, the identity record last)
    db_mod.delete_profile(real_db, "alice")
    db_mod.delete_history(real_db, "alice")
    db_mod.forum_purge_user(real_db, "alice")
    db_mod.message_delete_for_user(real_db, "alice")
    db_mod.notification_delete_for_user(real_db, "alice")
    assert db_mod.delete_user(real_db, "alice") is True
    # erased; bob's data intact with alice stripped out
    assert db_mod.get_user(real_db, "alice") is None
    assert db_mod.get_profile(real_db, "alice") is None
    assert db_mod.list_history(real_db, "alice") == []
    assert db_mod.forum_get_post(real_db, pa) is None
    post = db_mod.forum_get_post(real_db, pb)
    assert post["score"] == 1 and all(c["author"] != "alice" for c in db_mod.forum_list_comments(real_db, pb))
    assert db_mod.message_list_conversation(real_db, "alice", "bob") == []
    assert db_mod.notification_list(real_db, "bob") == []


def test_email_consent_and_export_against_mongo(db_mod, real_db):
    db_mod.create_user(real_db, "alice", "h1", "a@ex.com", display_name="Alice")
    assert db_mod.get_email_consent(real_db, "alice") is False           # default
    assert db_mod.set_email_consent(real_db, "alice", True) is True
    assert db_mod.get_email_consent(real_db, "alice") is True            # persisted
    bp = db_mod.forum_create_post(real_db, "bob", "B", "b", False)["id"]
    cid = db_mod.forum_add_comment(real_db, bp, "alice", "hi")["id"]
    db_mod.forum_vote(real_db, bp, "alice", 1)
    db_mod.forum_vote_comment(real_db, bp, cid, "alice", 1)
    db_mod.message_send(real_db, "alice", "bob", "hey")
    fx = db_mod.forum_export_user(real_db, "alice")
    assert fx["posts"] == [] and [c["body"] for c in fx["comments"]] == ["hi"] and len(fx["votes"]) == 2
    assert [m["body"] for m in db_mod.message_export_for_user(real_db, "alice")] == ["hey"]


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
    assert db_mod.forum_get_post(real_db, pid)["comment_count"] == 1   # #331: count on the post, comments elsewhere
    stored = db_mod.forum_list_comments(real_db, pid)
    assert len(stored) == 1 and stored[0]["author"] == "bob" and stored[0]["body"] == "nice"
    assert stored[0]["score"] == 0 and "votes" not in stored[0]        # internal tally not leaked
    # the votes-as-list fix: '.'/'$' usernames must be safe real-Mongo writes (would fail as field names)
    assert db_mod.forum_vote(real_db, pid, "bob.smith", 1) == 1
    assert db_mod.forum_vote(real_db, pid, "$admin", 1) == 2
    # comment votes use the same list-based tally, guarded by a nested-array CAS
    assert db_mod.forum_vote_comment(real_db, pid, cid, "bob.smith", 1) == 1
    assert db_mod.forum_vote_comment(real_db, pid, cid, "$admin", 1) == 2   # distinct users sum
    assert db_mod.forum_vote_comment(real_db, pid, cid, "bob.smith", -1) == 0  # same user replaces


def test_forum_vote_behaviour_against_mongo(db_mod, real_db):
    # Vote behaviour now lives ONLY on the atomic aggregation-pipeline update (the in-memory fake can't
    # execute a pipeline), so it's pinned here against real Mongo: set / same-user-replace / distinct-user
    # aggregate, votes stored as a LIST of {user,value}, and unknown post/comment -> None.
    pid = db_mod.forum_create_post(real_db, "alice", "T", "B", False)["id"]
    assert db_mod.forum_vote(real_db, pid, "alice", 1) == 1
    assert db_mod.forum_vote(real_db, pid, "alice", -1) == -1        # one vote per user -> replaces, not adds
    assert db_mod.forum_vote(real_db, pid, "bob", 1) == 0            # distinct users aggregate: -1 + 1
    raw = real_db.forum_posts.find_one({"id": pid})
    assert isinstance(raw["votes"], list)                           # a LIST, never a username-keyed dict
    assert {v["user"] for v in raw["votes"]} == {"alice", "bob"}
    assert db_mod.forum_vote(real_db, "nope", "alice", 1) is None    # unknown post -> None
    cid = db_mod.forum_add_comment(real_db, pid, "bob", "hi")["id"]
    assert db_mod.forum_vote_comment(real_db, "nope", cid, "carol", 1) is None            # unknown post
    assert db_mod.forum_vote_comment(real_db, pid, "no-such-comment", "carol", 1) is None  # unknown comment
    assert db_mod.forum_vote_comment(real_db, pid, cid, "carol", 1) == 1
    assert db_mod.forum_vote_comment(real_db, pid, cid, "carol", -1) == -1  # same user replaces on the comment too


def test_forum_vote_paths_bump_the_realtime_rev_against_mongo(db_mod, real_db):
    # Real-time push (SSE `event: forum`): the two vote mutations run the Mongo pipeline the fake can't, so
    # their rev-bump is pinned here. A successful post OR comment vote advances forum_get_rev; a vote on an
    # unknown post does NOT (nothing changed -> no ping).
    pid = db_mod.forum_create_post(real_db, "alice", "T", "B", False)["id"]
    cid = db_mod.forum_add_comment(real_db, pid, "bob", "hi")["id"]
    r0 = db_mod.forum_get_rev(real_db)
    assert db_mod.forum_vote(real_db, pid, "carol", 1) == 1
    r1 = db_mod.forum_get_rev(real_db)
    assert r1 == r0 + 1                                             # a post vote is a change
    assert db_mod.forum_vote_comment(real_db, pid, cid, "carol", 1) == 1
    assert db_mod.forum_get_rev(real_db) == r1 + 1                  # a comment vote is a change
    before = db_mod.forum_get_rev(real_db)
    assert db_mod.forum_vote(real_db, "nope", "carol", 1) is None   # unknown post -> no write
    assert db_mod.forum_get_rev(real_db) == before                  # ...and no bump


def test_forum_vote_is_atomic_under_concurrency(db_mod, real_db):
    # The atomic pipeline update must let many simultaneous voters on ONE hot post all succeed with the
    # correct final tally and NO spurious error. The old read-rebuild-CAS-retry loop could exhaust its
    # (8) retries under this contention and raise RuntimeError -> the route surfaced a 503 for a valid
    # vote on a perfectly healthy DB. Each write is atomic at the document level, so all N land.
    import threading
    pid = db_mod.forum_create_post(real_db, "author", "T", "B", False)["id"]
    n = 24
    barrier = threading.Barrier(n)
    errors, lock = [], threading.Lock()

    def cast(i):
        barrier.wait()                      # release all at once -> maximal contention on the one post
        try:
            db_mod.forum_vote(real_db, pid, f"user{i}", 1)
        except Exception as exc:            # noqa: BLE001 - the whole point is to catch a spurious raise
            with lock:
                errors.append(repr(exc))

    threads = [threading.Thread(target=cast, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"a valid concurrent vote raised on a healthy DB: {errors[:3]}"
    post = db_mod.forum_get_post(real_db, pid)
    assert post["score"] == n               # every distinct voter's +1 landed -> no lost update, no livelock


def test_forum_vote_same_user_concurrent_revote_nets_one(db_mod, real_db):
    # The same user firing many concurrent votes must end with exactly ONE vote for them (dedup holds
    # under contention): the pipeline drops their prior vote before appending, atomically, every time.
    import threading
    pid = db_mod.forum_create_post(real_db, "author", "T", "B", False)["id"]
    barrier = threading.Barrier(16)

    def cast():
        barrier.wait()
        db_mod.forum_vote(real_db, pid, "sam", 1)

    threads = [threading.Thread(target=cast) for _ in range(16)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert db_mod.forum_get_post(real_db, pid)["score"] == 1   # one net vote, not 16


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


def test_add_history_replaces_the_same_day_entry_against_mongo(db_mod, real_db):
    # issue #5: one row per UTC day. Two check-ins the same day -> the second REPLACES the first; a
    # different day is kept. Pinned on real Mongo because the same-day match is a nested-path $regex the
    # in-memory fake can't run. list_history returns entries oldest-first.
    db_mod.add_history(real_db, "alice", {"timestamp": "2026-07-15T06:00:00+00:00", "assessment": "Rest"})
    db_mod.add_history(real_db, "alice", {"timestamp": "2026-07-15T21:00:00+00:00", "assessment": "Ready"})
    db_mod.add_history(real_db, "alice", {"timestamp": "2026-07-16T07:00:00+00:00", "assessment": "Moderate"})
    hist = db_mod.list_history(real_db, "alice")
    assert [e["assessment"] for e in hist] == ["Ready", "Moderate"]   # the 15th's Rest was replaced by Ready
    # an entry without a parseable timestamp is appended, never dropped (defensive)
    db_mod.add_history(real_db, "alice", {"assessment": "Ready"})
    assert len(db_mod.list_history(real_db, "alice")) == 3


def test_dm_thread_read_is_bounded_and_indexed_against_mongo(db_mod, real_db):
    # #331: a DM thread reads a bounded, cursor-paged page off the two compound (participant-pair, created_at)
    # indexes, not a full-thread scan. Pinned on real Mongo because the $or + sort + limit is the SORT_MERGE
    # path the in-memory fake can't model. Order-strict assertions are avoided (wall-clock created_at can tie).
    db_mod.ensure_indexes(real_db)
    keys = [tuple(idx["key"].items()) for idx in real_db.messages.list_indexes()]
    assert (("sender", 1), ("recipient", 1), ("created_at", -1)) in keys
    assert (("recipient", 1), ("sender", 1), ("created_at", -1)) in keys
    for i in range(120):
        db_mod.message_send(real_db, "alice", "bob", f"m{i}")
    page = db_mod.message_list_conversation(real_db, "alice", "bob")
    assert len(page) == db_mod.MESSAGE_PAGE_DEFAULT              # a bounded page, never all 120 messages
    cursor = page[0]["created_at"]                              # oldest loaded -> page strictly older than it
    older = db_mod.message_list_conversation(real_db, "alice", "bob", before=cursor)
    assert all(m["created_at"] < cursor for m in older)        # every older-page row precedes the cursor
    assert len(db_mod.message_list_conversation(real_db, "alice", "bob", limit=99999999)) == db_mod.MESSAGE_PAGE_MAX


def test_history_view_read_is_bounded_and_indexed_against_mongo(db_mod, real_db):
    # #331: the History view reads the newest HISTORY_VIEW_CAP check-ins off the (username, entry.timestamp)
    # index; limit=None (the GDPR export) still returns everything.
    from datetime import date, timedelta
    db_mod.ensure_indexes(real_db)
    keys = [tuple(idx["key"].items()) for idx in real_db.analysis_history.list_indexes()]
    assert (("username", 1), ("entry.timestamp", -1)) in keys
    cap, base = db_mod.HISTORY_VIEW_CAP, date(2020, 1, 1)
    for i in range(cap + 5):                                          # distinct days -> distinct check-ins
        ts = f"{(base + timedelta(days=i)).isoformat()}T10:00:00Z"
        db_mod.add_history(real_db, "alice", {"assessment": "Ready", "timestamp": ts})
    view = db_mod.list_history(real_db, "alice", limit=cap)
    assert len(view) == cap                                          # bounded to the newest N
    assert view[0]["timestamp"] < view[-1]["timestamp"]             # oldest-first within the window
    assert view[-1]["timestamp"].startswith((base + timedelta(days=cap + 4)).isoformat())  # newest day present
    assert len(db_mod.list_history(real_db, "alice")) == cap + 5    # limit=None (export) = every entry


def test_history_set_recommendations_persists_by_timestamp_against_mongo(db_mod, real_db):
    # #354 backfill: recompute recs for a pre-#354 entry and persist them onto the row matched by its timestamp.
    db_mod.add_history(real_db, "alice", {"assessment": "Ready", "timestamp": "2026-06-01T07:00:00Z",
                                          "metrics": {"sleep_hours": 8}})
    assert db_mod.history_set_recommendations(real_db, "alice", "2026-06-01T07:00:00Z", ["Hydrate", 5]) is True
    entry = db_mod.list_history(real_db, "alice", limit=10)[-1]
    assert entry["recommendations"] == ["Hydrate", "5"]            # coerced to strings + persisted
    assert db_mod.history_set_recommendations(real_db, "alice", "no-such-ts", []) is False   # unknown ts -> no match


def test_inbox_summary_read_is_bounded_against_mongo(db_mod, real_db):
    # #331: the inbox derives its rows from a bounded read of recent messages + a bounded unread scan, and the
    # result is capped to `limit` — never the user's whole message history.
    db_mod.ensure_indexes(real_db)
    for peer in ("alice", "carol", "dave"):
        db_mod.message_send(real_db, peer, "bob", f"hi from {peer}")
    rows = db_mod.message_list_conversations(real_db, "bob")
    assert {r["peer"] for r in rows} == {"alice", "carol", "dave"}
    assert all(r["unread"] == 1 for r in rows)                      # one unread from each peer
    assert len(db_mod.message_list_conversations(real_db, "bob", limit=2)) == 2   # result capped to `limit`


def test_notification_feed_read_is_bounded_and_indexed_against_mongo(db_mod, real_db):
    # #331: notifications read newest-first off the (user, created_at) index, bounded by `limit`; limit=None
    # (the GDPR export) returns the full feed.
    db_mod.ensure_indexes(real_db)
    keys = [tuple(idx["key"].items()) for idx in real_db.notifications.list_indexes()]
    assert (("user", 1), ("created_at", -1)) in keys
    for i in range(db_mod.NOTIF_VIEW_CAP + 5):
        db_mod.notification_add(real_db, "bob", "dm", "a", "a", f"n{i}")
    assert len(db_mod.notification_list(real_db, "bob", limit=db_mod.NOTIF_VIEW_CAP)) == db_mod.NOTIF_VIEW_CAP
    assert len(db_mod.notification_list(real_db, "bob")) == db_mod.NOTIF_VIEW_CAP + 5   # limit=None (export) = all
