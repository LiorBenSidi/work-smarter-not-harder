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
