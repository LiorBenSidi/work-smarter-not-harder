"""Unit tests for the DM + notification seams in web/services/db.py (Lior's data layer).

Exercised against an in-memory fake collection — no Mongo, no Docker (the course's mocking technique).
These pin the behaviour contract the web stores depend on. Time is driven by a monkeypatched clock so
ordering is deterministic instead of racing the wall clock.
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"


@pytest.fixture
def db_mod():
    pytest.importorskip("pymongo")
    spec = importlib.util.spec_from_file_location("web_db_msgs_under_test", str(WEB / "services" / "db.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Cursor:
    """Iterable pymongo-cursor stand-in: supports .sort() + .limit(), and records the applied limit on the
    parent collection so a test can assert a read was BOUNDED (not an unlimited scan)."""

    def __init__(self, rows, coll=None):
        self._rows, self._coll = rows, coll

    def sort(self, field, direction=1):
        return _Cursor(sorted(self._rows, key=lambda d: d.get(field, 0), reverse=direction < 0), self._coll)

    def limit(self, n):
        if self._coll is not None:
            self._coll.last_limit = n
        return _Cursor(self._rows[:n] if n else self._rows, self._coll)

    def __iter__(self):
        return iter(self._rows)


class _Coll:
    """Minimal pymongo-collection stand-in supporting the ops the message/notification seams use — now
    including the `$or` + `$lt` cursor read the bounded DM-thread page (#331) needs."""

    def __init__(self):
        self.docs = []
        self.last_limit = None      # the n from the most recent find(...).limit(n), for read-bound assertions

    _OPS = ("$lt", "$lte", "$gt", "$gte", "$ne")

    def _match(self, doc, filt):
        for k, v in filt.items():
            if k == "$or":
                if not any(self._match(doc, sub) for sub in v):
                    return False
            elif isinstance(v, dict) and any(op in v for op in self._OPS):   # range/inequality operators
                val = doc.get(k)
                for op, bound in v.items():
                    if op == "$ne":
                        if val == bound:
                            return False
                    elif val is None:                                        # a comparison against a missing field never matches
                        return False
                    elif op == "$lt" and not val < bound:
                        return False
                    elif op == "$lte" and not val <= bound:
                        return False
                    elif op == "$gt" and not val > bound:
                        return False
                    elif op == "$gte" and not val >= bound:
                        return False
            elif doc.get(k) != v:
                return False
        return True

    def find(self, filt=None):
        return _Cursor([dict(d) for d in self.docs if self._match(d, filt or {})], self)

    def count_documents(self, filt=None):
        return sum(1 for d in self.docs if self._match(d, filt or {}))

    def insert_one(self, doc):
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id="x")

    def update_one(self, filt, update):
        for d in self.docs:
            if self._match(d, filt):
                d.update(update.get("$set", {}))
                return SimpleNamespace(matched_count=1)
        return SimpleNamespace(matched_count=0)

    def update_many(self, filt, update):
        n = 0
        for d in self.docs:
            if self._match(d, filt):
                d.update(update.get("$set", {}))
                n += 1
        return SimpleNamespace(matched_count=n)


class _DB:
    def __init__(self):
        self.messages = _Coll()
        self.notifications = _Coll()


class _Clock:
    """Deterministic monotonic clock -> each seam write gets a strictly-increasing created_at."""

    def __init__(self):
        self.v = 1000.0

    def time(self):
        self.v += 1.0
        return self.v


@pytest.fixture
def db(db_mod, monkeypatch):
    monkeypatch.setattr(db_mod, "time", _Clock())
    return _DB()


def test_thread_key_cannot_collide_on_delimiter_usernames(db_mod, db):
    # regression for the "|".join(sorted(pair)) collision: a username may contain any char, so a joined
    # id let a DIFFERENT pair address the same thread. Matching on the real {sender, recipient} can't.
    db_mod.message_send(db, "bob", "carol|dave", "private for carol|dave")
    assert db_mod.message_list_conversation(db, "bob|carol", "dave") == []          # colliding pair sees nothing
    assert [m["body"] for m in db_mod.message_list_conversation(db, "bob", "carol|dave")] \
        == ["private for carol|dave"]                                               # the real pair still resolves


def test_send_then_list_conversation_roundtrips(db_mod, db):
    db_mod.message_send(db, "alice", "bob", "hi bob")
    db_mod.message_send(db, "bob", "alice", "hi alice")
    thread = db_mod.message_list_conversation(db, "alice", "bob")
    assert [m["body"] for m in thread] == ["hi bob", "hi alice"]          # oldest first
    assert db_mod.message_list_conversation(db, "bob", "alice") == thread  # same thread, either order


def test_list_conversations_summarizes_unread(db_mod, db):
    db_mod.message_send(db, "alice", "bob", "one")
    db_mod.message_send(db, "alice", "bob", "two")
    convos = db_mod.message_list_conversations(db, "bob")
    assert len(convos) == 1
    assert convos[0]["peer"] == "alice"
    assert convos[0]["last_message"] == "two"
    assert convos[0]["unread"] == 2                                       # bob received both


def test_mark_read_clears_only_the_recipients_side(db_mod, db):
    db_mod.message_send(db, "alice", "bob", "yo")
    db_mod.message_mark_read(db, "bob", "alice")
    assert db_mod.message_list_conversations(db, "bob")[0]["unread"] == 0
    assert db_mod.message_list_conversation(db, "alice", "bob")[0]["read"] is True


def test_count_since_counts_only_the_sender_after_the_cutoff(db_mod, db):
    db_mod.message_send(db, "alice", "bob", "a")
    db_mod.message_send(db, "alice", "bob", "b")
    db_mod.message_send(db, "carol", "bob", "c")
    assert db_mod.message_count_since(db, "alice", 0) == 2                # only alice's sends
    assert db_mod.message_count_since(db, "alice", 9e18) == 0            # far-future cutoff -> none


def test_notification_add_list_newest_first_and_mark_read(db_mod, db):
    db_mod.notification_add(db, "bob", "dm", "alice", "alice", "from alice")
    db_mod.notification_add(db, "bob", "dm", "carol", "carol", "from carol")
    items = db_mod.notification_list(db, "bob")
    assert [n["text"] for n in items] == ["from carol", "from alice"]     # newest first
    db_mod.notification_mark_read(db, "bob")
    assert all(n["read"] for n in db_mod.notification_list(db, "bob"))


def test_notification_since_returns_only_newer(db_mod, db):
    first = db_mod.notification_add(db, "bob", "dm", "a", "a", "first")
    db_mod.notification_add(db, "bob", "dm", "c", "c", "second")
    newer = db_mod.notification_list(db, "bob", since=first["created_at"])
    assert [n["text"] for n in newer] == ["second"]


def test_notifications_are_per_user(db_mod, db):
    db_mod.notification_add(db, "bob", "dm", "alice", "alice", "for bob")
    assert db_mod.notification_list(db, "carol") == []                    # carol sees nothing


# ---- #331: the DM thread read is a BOUNDED, cursor-paged page (not a whole-thread load) ----
def test_conversation_page_is_bounded_and_clamped(db_mod, db):
    for i in range(120):
        db_mod.message_send(db, "alice", "bob", f"m{i}")
    default_page = db_mod.message_list_conversation(db, "alice", "bob")
    assert len(default_page) == db_mod.MESSAGE_PAGE_DEFAULT               # a default PAGE, never the whole 120-msg thread
    assert db.messages.last_limit == db_mod.MESSAGE_PAGE_DEFAULT          # the read was .limit()-bounded, not capped in memory
    huge = db_mod.message_list_conversation(db, "alice", "bob", limit=99999999)
    assert len(huge) == db_mod.MESSAGE_PAGE_MAX                           # ?limit=huge can't pull an unbounded slice
    assert db.messages.last_limit == db_mod.MESSAGE_PAGE_MAX


def test_conversation_default_page_is_the_newest_messages_oldest_first(db_mod, db):
    for i in range(60):
        db_mod.message_send(db, "alice", "bob", f"m{i}")
    page = [m["body"] for m in db_mod.message_list_conversation(db, "alice", "bob")]   # default 50
    assert len(page) == 50
    assert page[0] == "m10" and page[-1] == "m59"                         # the 50 most-recent (m10..m59), oldest-first


def test_conversation_before_cursor_pages_to_older(db_mod, db):
    for i in range(60):
        db_mod.message_send(db, "alice", "bob", f"m{i}")
    page1 = db_mod.message_list_conversation(db, "alice", "bob")          # newest 50: m10..m59
    oldest_at = page1[0]["created_at"]                                   # cursor = the oldest message loaded so far
    older = db_mod.message_list_conversation(db, "alice", "bob", before=oldest_at)
    assert [m["body"] for m in older] == [f"m{i}" for i in range(10)]     # the previous page (m0..m9), oldest-first
    assert all(m["created_at"] < oldest_at for m in older)               # every row strictly older than the cursor


# ---- #331: the inbox summary + notification feed are BOUNDED reads too ----
def test_inbox_summary_is_a_bounded_read(db_mod, db):
    # The inbox must derive its rows from a .limit()-bounded read of recent messages — never the user's whole
    # message history pulled into the app — and cap the result to `limit`.
    db_mod.message_send(db, "alice", "bob", "hi")
    db_mod.message_send(db, "carol", "bob", "yo")
    rows = db_mod.message_list_conversations(db, "bob")
    assert {r["peer"] for r in rows} == {"alice", "carol"}
    assert db.messages.last_limit == db_mod.CONVO_SCAN_CAP               # the read was .limit()-bounded, not a full scan
    assert len(db_mod.message_list_conversations(db, "bob", limit=1)) == 1   # result capped to `limit`


def test_notification_feed_is_bounded_and_since_filters_in_query(db_mod, db):
    # The feed read is newest-first, capped by `limit` (a .limit()-bounded read), and `since` filters in the
    # query (off the index) rather than loading everything and filtering in Python.
    first = db_mod.notification_add(db, "bob", "dm", "a", "a", "first")
    db_mod.notification_add(db, "bob", "dm", "c", "c", "second")
    db_mod.notification_add(db, "bob", "dm", "d", "d", "third")
    capped = db_mod.notification_list(db, "bob", limit=2)
    assert [n["text"] for n in capped] == ["third", "second"]            # the newest 2
    assert db.notifications.last_limit == 2                              # .limit()-bounded read
    newer = db_mod.notification_list(db, "bob", since=first["created_at"], limit=db_mod.NOTIF_VIEW_CAP)
    assert [n["text"] for n in newer] == ["third", "second"]             # `since` excluded the first, in-query
