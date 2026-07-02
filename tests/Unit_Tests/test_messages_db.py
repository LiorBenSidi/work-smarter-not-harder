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


class _Coll:
    """Minimal pymongo-collection stand-in supporting just the ops the message/notification seams use."""

    def __init__(self):
        self.docs = []

    def _match(self, doc, filt):
        return all(doc.get(k) == v for k, v in filt.items())

    def find(self, filt=None):
        return [dict(d) for d in self.docs if self._match(d, filt or {})]

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
