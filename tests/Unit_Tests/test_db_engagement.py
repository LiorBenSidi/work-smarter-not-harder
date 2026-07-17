"""Unit tests for `forum_received_engagement` in web/services/db.py — OWNER: Elad.

The received-engagement metric (GUIDELINES §3.3: like/dislike totals "in a personal area") is the
per-user sum of votes OTHERS cast on the user's posts and comments. Same harness idea as
`test_db.py`: db.py is loaded off disk and driven against a minimal in-memory collection, so these
pin the behaviour contract without Mongo. The fake implements only what the function uses (find()).
"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

WEB = Path(__file__).resolve().parents[2] / "web"


@pytest.fixture
def db_mod():
    pytest.importorskip("pymongo")
    spec = importlib.util.spec_from_file_location("web_db_engagement_under_test", str(WEB / "services" / "db.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Coll:
    """Minimal collection stand-in: find() filters by `author` — the only field forum_received_engagement
    scopes its forum_posts + forum_comments reads on (#331) — and records the filter + returned-row count
    so a test can assert the read was bounded to the user, not a full-collection scan."""

    def __init__(self, rows):
        self._rows = rows
        self.last_filter = "unset"     # records the query forum_received_engagement scopes the read with
        self.returned = None           # how many docs the read actually pulled — the scan-bound assertion

    def find(self, filt=None, *args, **kwargs):
        # forum_received_engagement scopes BOTH reads by `author` (#331). Record the filter + row count so a
        # test can assert the read was BOUNDED to the user, not a full-collection scan.
        self.last_filter = filt
        rows = list(self._rows)
        if filt and "author" in filt:
            rows = [r for r in rows if r.get("author") == filt["author"]]
        self.returned = len(rows)
        return rows


def _db(posts, comments=()):
    return SimpleNamespace(forum_posts=_Coll(posts), forum_comments=_Coll(comments))


def _post(author, votes=()):
    return {"id": "p", "author": author, "votes": list(votes)}


def _comment(author, votes=()):
    return {"id": "c", "post_id": "p", "author": author, "votes": list(votes)}


def test_votes_on_own_posts_and_comments_are_counted(db_mod):
    posts = [_post("alice", votes=[{"user": "bob", "value": 1}, {"user": "carol", "value": 1}])]
    comments = [_comment("alice", votes=[{"user": "bob", "value": -1}])]   # alice's comment, a downvote on it
    assert db_mod.forum_received_engagement(_db(posts, comments), "alice") == {"up": 2, "down": 1, "score": 1}


def test_a_user_with_no_content_or_votes_gets_zeros(db_mod):
    assert db_mod.forum_received_engagement(_db([]), "alice") == {"up": 0, "down": 0, "score": 0}
    posts = [_post("bob", votes=[{"user": "carol", "value": 1}])]
    assert db_mod.forum_received_engagement(_db(posts), "alice") == {"up": 0, "down": 0, "score": 0}


def test_own_votes_on_own_content_are_excluded(db_mod):
    """'Received' engagement is from the community — upvoting yourself must not inflate it."""
    posts = [_post("alice", votes=[{"user": "alice", "value": 1}, {"user": "bob", "value": 1}])]
    assert db_mod.forum_received_engagement(_db(posts), "alice") == {"up": 1, "down": 0, "score": 1}


def test_votes_on_an_anonymous_post_still_reach_its_real_author(db_mod):
    """An anonymous post hides the author from readers, not from the author's own metric."""
    posts = [{"id": "p", "author": "alice", "anonymous": True, "votes": [{"user": "bob", "value": -1}]}]
    assert db_mod.forum_received_engagement(_db(posts), "alice") == {"up": 0, "down": 1, "score": -1}


def test_votes_on_someone_elses_comment_under_my_post_are_not_mine(db_mod):
    """Engagement follows the AUTHOR of the voted item, not the owner of the thread."""
    posts = [_post("alice")]
    comments = [_comment("bob", votes=[{"user": "carol", "value": 1}])]   # bob's comment under alice's post
    assert db_mod.forum_received_engagement(_db(posts, comments), "alice") == {"up": 0, "down": 0, "score": 0}
    assert db_mod.forum_received_engagement(_db(posts, comments), "bob") == {"up": 1, "down": 0, "score": 1}


def test_missing_votes_fields_do_not_crash(db_mod):
    """Legacy docs may lack `votes` — the metric must tolerate them (malformed-doc guard)."""
    posts = [{"id": "p", "author": "alice"}]
    comments = [{"id": "c", "author": "alice"}]
    assert db_mod.forum_received_engagement(_db(posts, comments), "alice") == {"up": 0, "down": 0, "score": 0}


def test_the_reads_are_scoped_to_the_user_not_full_scans(db_mod):
    """#331 (scale/DoS): a profile view must NOT drag the whole forum_posts / forum_comments collections
    into Python. Both reads are scoped to the user (by author), so a forum with thousands of unrelated
    posts + comments costs the same as one with a handful. Correctness is unchanged."""
    posts = ([_post("alice", votes=[{"user": "bob", "value": 1}])]
             + [_post(f"stranger{i}", votes=[{"user": "x", "value": 1}]) for i in range(200)])
    comments = ([_comment("alice", votes=[{"user": "carol", "value": 1}])]
                + [_comment(f"other{i}", votes=[{"user": "x", "value": 1}]) for i in range(200)])
    db = _db(posts, comments)

    result = db_mod.forum_received_engagement(db, "alice")

    assert result == {"up": 2, "down": 0, "score": 2}          # correctness holds under the scoped reads
    # each read scoped by author -> only alice's 1 post + 1 comment pulled, not all 201 + 201
    assert db.forum_posts.last_filter == {"author": "alice"}
    assert db.forum_posts.returned == 1
    assert db.forum_comments.last_filter == {"author": "alice"}
    assert db.forum_comments.returned == 1
