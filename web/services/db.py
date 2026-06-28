"""MongoDB data layer (pymongo).

OWNERSHIP: the **thin core CRUD** below (the seam the web tier calls — users / profiles / history /
forum) + its own unique-constraint indexes (``ensure_indexes``) are Lior's; the **Mongo container**
and schema/perf tuning, the Forum real-time backbone (notifications / DM / media / seeding) and
rate-limiting stay Elad's. See docs/COLLABORATORS.md.

The web stores (web/app.py ``_Db*`` classes) call these functions with the db handle from ``get_db``.
Inputs are already type-validated at the route layer (NoSQL-injection defense) before they reach here.
Collections (DESIGN.md §2): ``users``, ``profiles``, ``analysis_history``, ``forum_posts``.
"""
import logging
import threading
import uuid

from pymongo import MongoClient

logger = logging.getLogger(__name__)

_client = None
_client_lock = threading.Lock()


def ensure_indexes(db):
    """Create the unique constraints the CRUD relies on (idempotent — safe to call repeatedly).

    A unique index on ``users.username`` is defence-in-depth behind ``create_user``'s atomic upsert
    (also guards against direct DB writes), and ``forum_posts.id`` keeps the opaque post ids unique.
    """
    db.users.create_index("username", unique=True)
    db.forum_posts.create_index("id", unique=True)


def get_db(mongo_uri):
    """Return the default database handle for `mongo_uri` (lazy, process-wide pymongo client).

    The client is built once under a lock (double-checked) so concurrent first-requests under a
    threaded/multi-worker server don't each open a connection pool. ``serverSelectionTimeoutMS`` makes
    a down Mongo fail fast (~5s) so the routes' try/except degrades to 503 instead of hanging. Indexes
    are ensured best-effort on first connect — if Mongo isn't ready yet it's logged and skipped, never
    fatal (the app-level checks still hold).
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
                try:
                    ensure_indexes(_client.get_default_database())
                except Exception:
                    logger.warning("index creation deferred — Mongo not ready", exc_info=True)
    return _client.get_default_database()


# ---- users (auth seam) ----
def get_user(db, username):
    """Return ``{"username", "password_hash"}`` for `username`, or None."""
    doc = db.users.find_one({"username": username})
    if doc is None:
        return None
    return {"username": doc["username"], "password_hash": doc["password_hash"]}


def create_user(db, username, password_hash):
    """Create the user if absent. Return True if created, False if the username already exists."""
    result = db.users.update_one(
        {"username": username},
        {"$setOnInsert": {"username": username, "password_hash": password_hash}},
        upsert=True,
    )
    return result.upserted_id is not None


# ---- profiles (F2 seam) ----
def get_profile(db, username):
    """Return the stored profile dict for `username`, or None."""
    doc = db.profiles.find_one({"username": username})
    return doc["profile"] if doc else None


def save_profile(db, username, profile):
    """Upsert the user's profile (last write wins)."""
    db.profiles.update_one({"username": username}, {"$set": {"profile": profile}}, upsert=True)


# ---- history (F8 read + the check-in write) ----
def list_history(db, username):
    """Return the user's analysis-history entries (oldest-first insertion order)."""
    return [doc["entry"] for doc in db.analysis_history.find({"username": username})]


def add_history(db, username, entry):
    """Append one analysis-history entry for the user (written by the daily check-in)."""
    db.analysis_history.insert_one({"username": username, "entry": entry})


# ---- forum (CRUD seam; real-time push + seeding stay Elad's) ----
def _shape(post):
    """Public projection of a forum post — drops the raw _id and the internal votes list."""
    return {"id": post["id"], "author": post["author"], "anonymous": post.get("anonymous", False),
            "title": post["title"], "body": post["body"],
            "score": post.get("score", 0), "comments": post.get("comments", [])}


def forum_create_post(db, author, title, body, anonymous):
    """Insert a post and return its public shape (opaque string id)."""
    post = {"id": uuid.uuid4().hex, "author": author, "anonymous": anonymous,
            "title": title, "body": body, "score": 0, "comments": [], "votes": []}
    db.forum_posts.insert_one(post)
    return _shape(post)


def forum_list_posts(db):
    """Return every post in public shape."""
    return [_shape(p) for p in db.forum_posts.find()]


def forum_get_post(db, post_id):
    """Return one post in public shape, or None if `post_id` is unknown."""
    post = db.forum_posts.find_one({"id": post_id})
    return _shape(post) if post else None


def forum_add_comment(db, post_id, author, body):
    """Append a comment; return it, or None if the post is unknown."""
    comment = {"author": author, "body": body}
    result = db.forum_posts.update_one({"id": post_id}, {"$push": {"comments": comment}})
    return comment if result.matched_count else None


def forum_vote(db, post_id, username, value):
    """Record one vote per user (re-voting replaces) and return the new score, or None if unknown.

    Votes are stored as a LIST of ``{"user", "value"}`` — never a dict keyed by username, since a
    username may contain ``.`` or ``$`` (the validator only bounds length), which are illegal/fragile
    as MongoDB field names.
    """
    post = db.forum_posts.find_one({"id": post_id})
    if post is None:
        return None
    votes = [v for v in post.get("votes", []) if v.get("user") != username]  # drop this user's prior vote
    votes.append({"user": username, "value": value})
    score = sum(v["value"] for v in votes)
    db.forum_posts.update_one({"id": post_id}, {"$set": {"votes": votes, "score": score}})
    return score
