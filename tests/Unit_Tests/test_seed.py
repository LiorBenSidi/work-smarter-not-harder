"""Unit tests for the cold-seed (fake clients + posts + comments). OWNER: Lior.

The seed is exercised two ways:
- here, against an in-memory fake db, so the orchestration —
  who gets created, idempotency, the backdated timeline, login-ability — runs on any machine with no
  Mongo; the one op the fake can't do (``forum_vote``'s server-side aggregation-pipeline update) is
  monkeypatched to an equivalent read-modify-write (the real pipeline is covered by ``test_db`` and by
  ``tests/Integration_Tests/test_seed_mongo.py`` against a live mongo:7).
"""
import importlib.util
import re
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

# importorskip, not a bare import: this is the ONE test file conftest's importorskip("flask") does not
# shield, so in a lint-only venv (the README quickstart: ruff/bandit/pytest, no requirements.txt) a bare
# import errored COLLECTION itself and failed the pre-push hook before a single test could skip (#416).
werkzeug_security = pytest.importorskip("werkzeug.security", reason="app deps not installed (pip install -r requirements.txt)")
check_password_hash = werkzeug_security.check_password_hash

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

    @staticmethod
    def _value(doc, path):
        """Read a possibly-dotted key ('entry.timestamp'), the way Mongo addresses a subdocument."""
        cur = doc
        for part in path.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    def _match(self, doc, filt):
        for key, expected in filt.items():
            actual = self._value(doc, key)
            # add_history dedupes a calendar day with {"entry.timestamp": {"$regex": "^YYYY-MM-DD"}},
            # so the fake has to understand that one operator to hold a one-row-per-day log.
            if isinstance(expected, dict) and "$regex" in expected:
                if not isinstance(actual, str) or not re.search(expected["$regex"], actual):
                    return False
            elif actual != expected:
                return False
        return True

    def find_one(self, filt):
        return next((dict(d) for d in self.docs if self._match(d, filt)), None)

    def delete_many(self, filt):
        keep = [d for d in self.docs if not self._match(d, filt)]
        removed = len(self.docs) - len(keep)
        self.docs[:] = keep
        return SimpleNamespace(deleted_count=removed)

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
    """The seed data is validated before it is ever applied: handles and emails unique, every author a real seeded user, and every comment attached to a post that exists and dated after it."""
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


def test_seed_ships_enough_content_to_look_populated(seed_mod):
    """The seed ships enough users, posts and comments that a first-time visitor lands on a forum that looks alive rather than on an empty page."""
    assert len(seed_mod.SEED_USERS) >= 2
    assert len(seed_mod.SEED_POSTS) >= 2
    assert len(seed_mod.SEED_COMMENTS) >= 2


# --------------------------------------------------------------- behaviour (fake db)

def test_apply_seed_creates_the_fake_clients_posts_and_comments(seed_mod, db_mod, db, monkeypatch):
    """Applying the seed creates exactly what it declares — the counts it reports match what actually landed in the store, so a partial seed cannot pass as a complete one."""
    _patch_post_vote(monkeypatch, db_mod)
    result = seed_mod.apply_seed(db_mod, db)

    assert result == {"users": len(seed_mod.SEED_USERS),
                      "posts": len(seed_mod.SEED_POSTS),
                      "comments": len(seed_mod.SEED_COMMENTS)}
    assert len(db.users.docs) == len(seed_mod.SEED_USERS)
    assert len(db.forum_posts.docs) == len(seed_mod.SEED_POSTS)
    assert len(db.forum_comments.docs) == len(seed_mod.SEED_COMMENTS)


def test_each_post_carries_its_real_comment_count(seed_mod, db_mod, db, monkeypatch):
    """Each seeded post's comment counter matches the comments actually created for it, so the feed never advertises a count the thread cannot show."""
    _patch_post_vote(monkeypatch, db_mod)
    seed_mod.apply_seed(db_mod, db)
    expected = {}
    for post_index, *_ in seed_mod.SEED_COMMENTS:
        expected[post_index] = expected.get(post_index, 0) + 1
    posts_in_order = db.forum_posts.docs  # insertion order == SEED_POSTS order
    for i, post in enumerate(posts_in_order):
        assert post["comment_count"] == expected.get(i, 0)


def test_likes_land_as_positive_scores(seed_mod, db_mod, db, monkeypatch):
    """Seeded votes produce real positive scores, so a visitor does not meet a flat wall of zeros that makes voting look broken."""
    _patch_post_vote(monkeypatch, db_mod)
    seed_mod.apply_seed(db_mod, db)
    scored = [p for p in db.forum_posts.docs if p["score"] > 0]
    assert scored, "at least some seeded posts should carry likes so the forum isn't a flat zero-score wall"
    for post_index, _voter in seed_mod.SEED_POST_VOTES[:1]:
        votes = len([v for v in seed_mod.SEED_POST_VOTES if v[0] == post_index])
        assert db.forum_posts.docs[post_index]["score"] == votes  # each seed vote is +1, distinct voters


def test_content_is_backdated_onto_a_recent_timeline(seed_mod, db_mod, db, monkeypatch):
    """Seeded content is spread backwards across distinct recent times rather than all stamped with the moment of seeding, so the feed reads as a history instead of one burst."""
    _patch_post_vote(monkeypatch, db_mod)
    now = time.time()
    seed_mod.apply_seed(db_mod, db)
    created = [p["created_at"] for p in db.forum_posts.docs]
    assert all(ts < now for ts in created), "every seeded post must be backdated, not stamped 'now'"
    assert len(set(created)) == len(created), "posts should spread across distinct times, not pile on one instant"
    # oldest seeded post is ~14 days back; nothing should be in the future.
    assert min(created) <= now - 10 * seed_mod.DAY


def test_seeded_accounts_can_actually_log_in(seed_mod, db_mod, db, monkeypatch):
    """A seeded persona is only useful if it is a real account: its stored hash must verify against the seed password, so anyone can sign in as one and look around."""
    _patch_post_vote(monkeypatch, db_mod)
    seed_mod.apply_seed(db_mod, db)
    a_user = db.users.find_one({"username": "coach_maya"})
    assert a_user is not None
    assert check_password_hash(a_user["password_hash"], seed_mod.SEED_PASSWORD)


def test_apply_seed_is_idempotent(seed_mod, db_mod, db, monkeypatch):
    """Re-running the seed creates nothing new, so a container restart cannot quietly multiply the demo content every time it boots."""
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


# ---------------------------------------------------------------------------------------------
# The population the seed grew into: profiles, check-in history, DM threads, notifications, media.
# `_seed_forum`'s content was always covered above; these cover everything added alongside it.
# ---------------------------------------------------------------------------------------------

class _FakeMedia:
    """The media contract the seed uses — mirrors tests/conftest.py's FakeMedia (add + bind)."""

    def __init__(self):
        self.records = {}

    def add(self, media_id, owner, mime, size):
        self.records[media_id] = {"id": media_id, "owner": owner, "mime": mime, "size": size,
                                  "target_type": None, "target_id": None, "peers": None}

    def bind(self, media_id, owner, target_type, target_id, peers=None):
        rec = self.records.get(media_id)
        if not rec or rec["owner"] != owner:
            return False
        rec.update(target_type=target_type, target_id=target_id, peers=list(peers) if peers else None)
        return True


def _seed_all(seed_mod, db_mod, db, monkeypatch, **kw):
    _patch_post_vote(monkeypatch, db_mod)
    return seed_mod.apply_seed(db_mod, db, **kw)


def test_profiles_span_every_tier(seed_mod, db_mod, db, monkeypatch):
    """The seeded population must exercise beginner AND intermediate AND advanced.

    The tier is derived from which optional fields a profile carries (routes/profile.derive_tier), so
    a seed where everyone filled in the same things would demo only one third of PROPOSAL-v2 §3 —
    and the Advanced-tier balance analysis would never fire for anyone.
    """
    _seed_all(seed_mod, db_mod, db, monkeypatch)
    saved = {d["username"]: d for d in db.profiles.docs}
    assert len(saved) == len(seed_mod.CONTENT.PROFILES), "every athlete should get a profile"

    def tier(p):
        if p.get("training_program"):
            return "advanced"
        return "intermediate" if (p.get("equipment") or p.get("split_preference")) else "beginner"

    tiers = {tier(d.get("profile", d)) for d in saved.values()}
    assert tiers == {"beginner", "intermediate", "advanced"}, f"tiers present: {sorted(tiers)}"


def test_history_is_one_row_per_day_and_honours_the_gaps(seed_mod, db_mod, db, monkeypatch):
    """A heatmap with no holes looks generated, and two rows for one day would break the day key.

    ``add_history`` treats a calendar day as a single reading, so a seeded log must contain each day
    at most once; the per-athlete ``gaps`` are the days that athlete simply did not log.
    """
    _seed_all(seed_mod, db_mod, db, monkeypatch)
    rows = db.analysis_history.docs
    for handle, shape in seed_mod.CONTENT.HISTORY.items():
        mine = [r for r in rows if r["username"] == handle]
        assert len(mine) == shape["days"] - len(set(shape["gaps"])), f"{handle} wrote the wrong number of days"
        days = [r["entry"]["timestamp"][:10] for r in mine]
        assert len(set(days)) == len(days), f"{handle} has two entries on one calendar day"


def test_history_is_scored_by_the_real_model_when_one_is_reachable(seed_mod, db_mod, db, monkeypatch):
    """Every stored assessment must come from the model the dashboard asks, not a local rule.

    The app picks the displayed state with ``_choose_state``'s trained Ready threshold. A history
    scored by any other rule can read "Ready" in the heatmap while the dashboard reads "Rest" for the
    same numbers — a contradiction a reviewer sees on one screen. This pins that the seed calls the
    real scorer and stores exactly what it returns.
    """
    calls = []

    class _Client:
        @staticmethod
        def build_features(profile, metrics, **extra):
            return {**profile, **metrics, **extra}

        @staticmethod
        def predict(url, features):
            calls.append(url)
            return {"state": "Moderate", "proba": {"Moderate": 0.9, "Rest": 0.05, "Ready": 0.05},
                    "recommendations": ["from the model"], "calories": 1234}

    monkeypatch.setattr(seed_mod, "_load_ai_client", lambda: _Client)
    _seed_all(seed_mod, db_mod, db, monkeypatch, ai_url="http://ai:5000")

    assert calls, "the seed must ask the model rather than scoring locally"
    stored = db.analysis_history.docs
    assert {r["entry"]["assessment"] for r in stored} == {"Moderate"}
    assert stored[0]["entry"]["recommendations"] == ["from the model"]
    assert stored[0]["entry"]["calories"] == 1234


def test_history_falls_back_offline_and_stops_retrying(seed_mod, db_mod, db, monkeypatch):
    """When ai never answers the seed must still produce a usable history, and must not retry per row.

    Retrying a dead service once per check-in would turn a 500-row seed into 500 timeouts.
    """
    attempts = []

    class _DeadClient:
        @staticmethod
        def build_features(profile, metrics, **extra):
            return {**profile, **metrics}

        @staticmethod
        def predict(url, features):
            attempts.append(url)
            return None                      # ai unavailable

    monkeypatch.setattr(seed_mod, "_load_ai_client", lambda: _DeadClient)
    _seed_all(seed_mod, db_mod, db, monkeypatch, ai_url="http://ai:5000")

    assert len(attempts) == 1, f"a dead ai must be given up on after one try, not {len(attempts)}"
    assert db.analysis_history.docs, "history must still be written when ai is down"
    assert all(r["entry"]["assessment"] in {"Ready", "Moderate", "Rest"} for r in db.analysis_history.docs)


def test_dm_threads_land_in_order_with_a_real_unread_tail(seed_mod, db_mod, db, monkeypatch):
    """Conversations should read like conversations, and the unread badge should be neither 0 nor absurd."""
    _seed_all(seed_mod, db_mod, db, monkeypatch)
    sent = db.messages.docs
    expected = sum(len(thread) for _a, _b, thread in seed_mod.CONTENT.DM_THREADS)
    assert len(sent) == expected

    for a, b, thread in seed_mod.CONTENT.DM_THREADS:
        mine = [m for m in sent if {m["sender"], m["recipient"]} == {a, b}]
        assert [m["body"] for m in mine] == [body for _s, body, _age, _media in thread], \
            f"the {a}/{b} thread is out of order"
        unread = [m for m in mine if not m.get("read")]
        assert 0 < len(unread) <= 2, f"the {a}/{b} thread should end unread, not {len(unread)} of {len(mine)}"


def test_notifications_are_derived_and_never_self_addressed(seed_mod, db_mod, db, monkeypatch):
    """Notifications must mirror what the routes would raise — including never notifying you about yourself.

    They are derived from the seeded votes and DMs rather than hand-listed, so this also guards the
    shape: type "dm" (not "message"), and name-LESS text, which is what forum._notify_vote stores so
    that a later rename re-resolves instead of freezing a stale name into the row.
    """
    _seed_all(seed_mod, db_mod, db, monkeypatch)
    notes = db.notifications.docs
    assert notes, "the seeded votes and DMs should have raised notifications"
    assert not [n for n in notes if n["user"] == n["actor"]], "a user must never be notified about themselves"

    # The line above passes vacuously on the shipped data — it contains no self-vote, so the guard is
    # never reached and the assertion would hold even with the guard deleted (caught by mutation
    # testing). Force the case the guard exists for: a voter voting on their OWN post.
    own = next(i for i, (author, *_rest) in enumerate(seed_mod.SEED_POSTS) if author)
    author = seed_mod.SEED_POSTS[own][0]
    monkeypatch.setattr(seed_mod, "SEED_POST_VOTES", [(own, author)])
    fresh = _DB()
    _seed_all(seed_mod, db_mod, fresh, monkeypatch)
    assert not [n for n in fresh.notifications.docs if n["user"] == n["actor"]], \
        "a self-vote must raise no notification — routes/forum._notify_vote returns early on it"
    assert {n["type"] for n in notes} <= {"vote", "dm"}, "only the two types the routes raise"
    for n in notes:
        assert n["actor"] not in n["text"], f"notification text must stay name-less: {n['text']!r}"


def test_media_is_bound_to_its_target_using_the_stores_own_naming(seed_mod, db_mod, db, monkeypatch, tmp_path):
    """Attachments must reach BOTH posts and DMs, and the bytes must be findable by the serve route.

    media_store serves `<media_id><ext>`; if the seed wrote any other filename the record would exist
    and the image would 404 — the failure a reviewer notices first.
    """
    media = _FakeMedia()
    _seed_all(seed_mod, db_mod, db, monkeypatch, media=media, media_root=str(tmp_path))

    assert media.records, "no attachments were bound"
    targets = {r["target_type"] for r in media.records.values()}
    assert targets == {"post", "dm"}, f"attachments should cover posts AND DMs, got {targets}"

    for media_id, rec in media.records.items():
        ext = ".mp4" if rec["mime"] == "video/mp4" else ".jpg"
        assert (tmp_path / f"{media_id}{ext}").exists(), "bytes must be stored as <media_id><ext>"
        if rec["target_type"] == "dm":
            assert rec["peers"] and len(rec["peers"]) == 2, "a DM attachment is served to its two participants"


def test_a_second_run_changes_nothing_and_force_is_off_by_default(seed_mod, db_mod, db, monkeypatch):
    """The seed is safe to re-run, and the one switch that makes it unsafe must be opt-in.

    `force` exists for re-seeding a box that already holds content. Defaulting it on — or letting a
    later refactor flip it — would duplicate every post on each run, since post ids are random and no
    unique index dedupes them.
    """
    _seed_all(seed_mod, db_mod, db, monkeypatch)
    before = (len(db.forum_posts.docs), len(db.analysis_history.docs), len(db.messages.docs))

    second = seed_mod.apply_seed(db_mod, db)
    assert second == {"users": 0, "posts": 0, "comments": 0}
    assert (len(db.forum_posts.docs), len(db.analysis_history.docs), len(db.messages.docs)) == before

    forced = seed_mod.apply_seed(db_mod, db, force=True)
    assert forced["posts"] == len(seed_mod.SEED_POSTS), "force=True must actually re-seed"
    assert len(db.forum_posts.docs) > before[0], "a forced run adds content (which is why it is opt-in)"


def test_an_unwritable_media_root_costs_the_attachments_not_the_whole_seed(seed_mod, db_mod, db, monkeypatch):
    """`MEDIA_ROOT` defaults to the CONTAINER's path (`/app/media`), but db/README documents running
    this seed straight from a host — where that path is neither present nor creatable.

    Before this guard the `mkdir` raised and took the entire run with it: no users, no forum, no
    history, from a command the docs tell you to use. Attachments are the only thing that can
    reasonably fail there, so they are the only thing that may be lost.
    """
    result = _seed_all(seed_mod, db_mod, db, monkeypatch,
                       media=_FakeMedia(), media_root="/app/media")   # unwritable on any host

    assert result["posts"] == len(seed_mod.SEED_POSTS), "the forum must still be seeded"
    assert db.users.docs, "users must still be created"
    assert db.analysis_history.docs, "history must still be written"
