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


class _Posts:
    def __init__(self, rows):
        self._rows = rows

    def find(self, *args, **kwargs):
        return list(self._rows)


def _db(posts):
    return SimpleNamespace(forum_posts=_Posts(posts))


def _post(author, votes=(), comments=()):
    return {"id": "p", "author": author, "votes": list(votes), "comments": list(comments)}


def _comment(author, votes=()):
    return {"id": "c", "author": author, "votes": list(votes)}


def test_votes_on_own_posts_and_comments_are_counted(db_mod):
    posts = [
        _post("alice", votes=[{"user": "bob", "value": 1}, {"user": "carol", "value": 1}]),
        _post("bob", comments=[_comment("alice", votes=[{"user": "bob", "value": -1}])]),
    ]
    assert db_mod.forum_received_engagement(_db(posts), "alice") == {"up": 2, "down": 1, "score": 1}


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
    posts = [{"id": "p", "author": "alice", "anonymous": True,
              "votes": [{"user": "bob", "value": -1}], "comments": []}]
    assert db_mod.forum_received_engagement(_db(posts), "alice") == {"up": 0, "down": 1, "score": -1}


def test_votes_on_someone_elses_comment_under_my_post_are_not_mine(db_mod):
    """Engagement follows the AUTHOR of the voted item, not the owner of the thread."""
    posts = [_post("alice", comments=[_comment("bob", votes=[{"user": "carol", "value": 1}])])]
    assert db_mod.forum_received_engagement(_db(posts), "alice") == {"up": 0, "down": 0, "score": 0}
    assert db_mod.forum_received_engagement(_db(posts), "bob") == {"up": 1, "down": 0, "score": 1}


def test_missing_votes_fields_do_not_crash(db_mod):
    """Legacy docs may lack `votes`/`comments` — the metric must tolerate them (malformed-doc guard)."""
    posts = [{"id": "p", "author": "alice"}, {"id": "q", "author": "alice", "comments": [{"author": "alice"}]}]
    assert db_mod.forum_received_engagement(_db(posts), "alice") == {"up": 0, "down": 0, "score": 0}
