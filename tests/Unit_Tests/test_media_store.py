"""Unit tests for the Mongo-backed media index `DbMedia` in web/services/media_store.py — OWNER: Elad.

The integration suite drives the media routes against the in-memory `FakeMedia`; these pin the
`DbMedia` (real Mongo) side without a database, by injecting a minimal recording collection through
`services.db.get_db`. Focus: the #331 read bound — listing one target's attachments must be an indexed,
bounded read, never a scan of the whole media collection.
"""
import importlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"


class _Cursor:
    """Records the .sort()/.limit() a caller chains, and yields the (already-filtered) rows."""

    def __init__(self, rows):
        self._rows = rows
        self.sort_call = None
        self.limit_call = None

    def sort(self, key, direction):
        self.sort_call = (key, direction)
        self._rows = sorted(self._rows, key=lambda d: d.get(key, 0), reverse=direction < 0)
        return self

    def limit(self, n):
        self.limit_call = n
        self._rows = self._rows[:n]
        return self

    def __iter__(self):
        return iter(self._rows)


class _Coll:
    def __init__(self, docs):
        self.docs = docs
        self.indexes = []
        self.cursors = []

    def create_index(self, spec, **kwargs):
        self.indexes.append(spec)

    def find(self, filt):
        rows = [d for d in self.docs
                if all(d.get(k) == v for k, v in filt.items())]
        cur = _Cursor(rows)
        self.cursors.append(cur)
        return cur

    def delete_many(self, filt):
        doomed = [d for d in self.docs if all(d.get(k) == v for k, v in filt.items())]
        self.docs = [d for d in self.docs if d not in doomed]
        return SimpleNamespace(deleted_count=len(doomed))


@pytest.fixture
def media_mod():
    pytest.importorskip("pymongo")
    sys.path.insert(0, str(WEB))
    try:
        import services.db as db_mod  # noqa: F401  (must be importable for media_store's late import)
        mod = importlib.import_module("services.media_store")
        return importlib.reload(mod)
    finally:
        sys.path.remove(str(WEB))


def _dbmedia(media_mod, monkeypatch, docs):
    coll = _Coll(list(docs))
    import services.db as db_mod
    monkeypatch.setattr(db_mod, "get_db", lambda uri: {"media": coll})
    app = SimpleNamespace(config={"MONGO_URI": "mongodb://x", "MEDIA_MAX_ATTACHMENTS_PER_TARGET": 3})
    return media_mod.DbMedia(app), coll


def _rec(mid, tt="post", tid="p1", ts=0.0):
    return {"_id": mid, "owner": "alice", "mime": "image/png", "size": 1,
            "target_type": tt, "target_id": tid, "peers": None, "created_at": ts}


def test_list_for_target_is_backed_by_a_compound_index(media_mod, monkeypatch):
    store, coll = _dbmedia(media_mod, monkeypatch, [])
    store.list_for_target("post", "p1")
    assert [("target_type", 1), ("target_id", 1), ("created_at", 1)] in coll.indexes


def test_list_for_target_bounds_the_read_to_the_cap(media_mod, monkeypatch):
    docs = [_rec(f"m{i}", ts=float(i)) for i in range(10)]     # 10 bound to the same target
    store, coll = _dbmedia(media_mod, monkeypatch, docs)
    out = store.list_for_target("post", "p1")
    assert len(out) == 3                                       # capped at MEDIA_MAX_ATTACHMENTS_PER_TARGET
    assert coll.cursors[-1].limit_call == 3                    # the bound is pushed to the DB, not sliced after
    assert coll.cursors[-1].sort_call == ("created_at", 1)     # oldest-first, stable ordering


def test_list_for_target_only_returns_the_matching_target(media_mod, monkeypatch):
    docs = [_rec("a", tid="p1"), _rec("b", tid="p2"), _rec("c", tid="p1")]
    store, _ = _dbmedia(media_mod, monkeypatch, docs)
    assert {r["id"] for r in store.list_for_target("post", "p1")} == {"a", "c"}


# --------------------------------------------------------------------------- erasure (#507)
# Media used to be the ONE store that survived account deletion: the index exposed no owner-scoped
# read or delete, so `delete_account` had nothing to call and a deleted user's blobs stayed in Mongo
# AND on the volume. These pin both halves — documents and bytes — and the owner scoping that keeps
# one user's erasure from touching anyone else's uploads.


def _owned(mid, owner, mime="image/png", ts=0.0):
    return {"_id": mid, "owner": owner, "mime": mime, "size": 1,
            "target_type": None, "target_id": None, "peers": None, "created_at": ts}


def test_list_for_owner_is_backed_by_an_owner_index(media_mod, monkeypatch):
    """Without it, erasing one account scans the whole (growing) media collection."""
    store, coll = _dbmedia(media_mod, monkeypatch, [])
    store.list_for_owner("alice")
    assert "owner" in coll.indexes


def test_list_for_owner_returns_only_that_users_uploads(media_mod, monkeypatch):
    docs = [_owned("a", "alice"), _owned("b", "bob"), _owned("c", "alice")]
    store, _ = _dbmedia(media_mod, monkeypatch, docs)
    assert {r["id"] for r in store.list_for_owner("alice")} == {"a", "c"}


def test_delete_for_owner_removes_only_that_users_documents(media_mod, monkeypatch):
    """Erasure is owner-scoped: deleting alice must not erase bob's uploads."""
    docs = [_owned("a", "alice"), _owned("b", "bob"), _owned("c", "alice")]
    store, coll = _dbmedia(media_mod, monkeypatch, docs)
    assert store.delete_for_owner("alice") == 2
    assert [d["_id"] for d in coll.docs] == ["b"]


def test_purge_owner_erases_the_documents_and_the_files(media_mod, monkeypatch, tmp_path):
    """The whole point of #507: a deleted account leaves neither a record nor a blob behind."""
    docs = [_owned("a", "alice", "image/png"), _owned("v", "alice", "video/mp4"),
            _owned("b", "bob", "image/png")]
    store, coll = _dbmedia(media_mod, monkeypatch, docs)
    for name in ("a.png", "v.mp4", "b.png"):
        (tmp_path / name).write_bytes(b"x")

    documents, files = media_mod.purge_owner(store, str(tmp_path), "alice")

    assert (documents, files) == (2, 2)
    assert [d["_id"] for d in coll.docs] == ["b"]                      # bob's record untouched
    assert not (tmp_path / "a.png").exists()
    assert not (tmp_path / "v.mp4").exists()                           # the mp4 extension resolved too
    assert (tmp_path / "b.png").exists()                               # bob's file untouched


def test_purge_owner_still_erases_the_document_when_the_blob_is_already_gone(media_mod, monkeypatch,
                                                                            tmp_path):
    """A record whose file was already lost (rotated volume) must not abort erasure — otherwise one
    missing blob leaves the rest of the user's media in the database forever."""
    docs = [_owned("gone", "alice"), _owned("here", "alice")]
    store, coll = _dbmedia(media_mod, monkeypatch, docs)
    (tmp_path / "here.png").write_bytes(b"x")                          # 'gone.png' deliberately absent

    documents, files = media_mod.purge_owner(store, str(tmp_path), "alice")

    assert documents == 2                                              # both records erased
    assert files == 1                                                  # only one file was there to remove
    assert coll.docs == []
    assert not (tmp_path / "here.png").exists()
