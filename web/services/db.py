"""MongoDB data layer (pymongo).

OWNERSHIP: the **thin core CRUD** below (the seam the web tier calls — users / profiles / history /
forum), its indexes (``ensure_indexes``), the **document-shape validators** (``ensure_schema``) and the
**seed** script (``db/seed.py``) are Lior's; the Forum real-time backbone (notifications / DM / media),
rate-limiting and the Azure deploy are Elad's. See docs/COLLABORATORS.md.

The web stores (web/app.py ``_Db*`` classes) call these functions with the db handle from ``get_db``.
Inputs are already type-validated at the route layer (NoSQL-injection defense) before they reach here.
Collections (DESIGN.md §2): ``users``, ``profiles``, ``analysis_history``, ``forum_posts``.
"""
import logging
import threading
import time
import uuid

from pymongo import MongoClient, ReturnDocument
from pymongo.errors import CollectionInvalid, DuplicateKeyError, OperationFailure

logger = logging.getLogger(__name__)

_VOTE_RETRIES = 8        # optimistic-concurrency retries for forum_vote (see its docstring)

_client = None
_client_lock = threading.Lock()


def ensure_indexes(db):
    """Create the indexes the CRUD relies on (idempotent — safe to call repeatedly).

    Unique constraints (integrity): ``users.username`` is defence-in-depth behind ``create_user``'s
    atomic upsert (also guards direct DB writes); ``forum_posts.id`` keeps the opaque post ids unique;
    ``profiles.username`` enforces one profile per user (matches ``save_profile``'s upsert key).
    Performance: ``analysis_history.username`` makes ``list_history`` a per-user index scan rather than
    a full-collection scan as history grows.
    """
    db.users.create_index("username", unique=True)
    db.forum_posts.create_index("id", unique=True)
    db.profiles.create_index("username", unique=True)
    db.analysis_history.create_index("username")
    # Social layer: threads + inbox filter on the real sender/recipient username fields; poll on user.
    db.messages.create_index("sender")
    db.messages.create_index("recipient")
    db.notifications.create_index("user")


# Document-shape validators ($jsonSchema) — defence-in-depth behind the route-layer validation: the DB
# itself rejects a structurally-wrong document (a direct write, a buggy migration). Only the load-bearing
# string fields are required/typed; score/comments/votes pass as unconstrained extra fields so every real
# CRUD write validates. validationLevel "strict" => validate ALL inserts AND updates (a later bad write to
# a legacy-invalid doc is rejected too) — our real writes are all valid, so nothing legitimate is blocked.
_NAMESPACE_NOT_FOUND = 26      # MongoDB OperationFailure code: the collection doesn't exist yet
_SCHEMAS = {
    "users": {"bsonType": "object", "required": ["username", "password_hash"],
              "properties": {"username": {"bsonType": "string"}, "password_hash": {"bsonType": "string"},
                             "email": {"bsonType": "string"}, "display_name": {"bsonType": "string"}}},
    "profiles": {"bsonType": "object", "required": ["username", "profile"],
                 "properties": {"username": {"bsonType": "string"}, "profile": {"bsonType": "object"}}},
    "analysis_history": {"bsonType": "object", "required": ["username", "entry"],
                         "properties": {"username": {"bsonType": "string"}, "entry": {"bsonType": "object"}}},
    "forum_posts": {"bsonType": "object", "required": ["id", "author", "title", "body"],
                    "properties": {"id": {"bsonType": "string"}, "author": {"bsonType": "string"},
                                   "title": {"bsonType": "string"}, "body": {"bsonType": "string"}}},
    "messages": {"bsonType": "object", "required": ["id", "sender", "recipient", "body"],
                 "properties": {"id": {"bsonType": "string"}, "sender": {"bsonType": "string"},
                                "recipient": {"bsonType": "string"}, "body": {"bsonType": "string"}}},
    "notifications": {"bsonType": "object", "required": ["id", "user", "type", "text"],
                      "properties": {"id": {"bsonType": "string"}, "user": {"bsonType": "string"},
                                     "type": {"bsonType": "string"}, "text": {"bsonType": "string"}}},
}


def ensure_schema(db):
    """Apply the $jsonSchema validators to every collection (idempotent, best-effort, race-tolerant).

    Per collection: ``collMod`` it; if it doesn't exist yet (NamespaceNotFound), create it with the
    validator; if a concurrent writer auto-created it in between, fall back to ``collMod``. Any OTHER
    failure (e.g. a restricted app user without ``collMod`` rights, or a view) is logged and skipped —
    the route-layer validation still holds, and an admin / the seed script applies it for real. So one
    unprivileged or unusual collection never aborts provisioning for the rest.
    """
    for name, schema in _SCHEMAS.items():
        validator = {"$jsonSchema": schema}
        try:
            db.command("collMod", name, validator=validator, validationLevel="strict")
            continue
        except OperationFailure as exc:
            if getattr(exc, "code", None) != _NAMESPACE_NOT_FOUND:
                logger.warning("schema validator skipped for %s (not authorized / not a collection)", name)
                continue
        try:                                                  # collection absent -> create it with the validator
            db.create_collection(name, validator=validator, validationLevel="strict")
        except (CollectionInvalid, OperationFailure):         # raced a concurrent auto-create -> collMod instead
            try:
                db.command("collMod", name, validator=validator, validationLevel="strict")
            except OperationFailure:
                logger.warning("schema validator skipped for %s", name)


def get_db(mongo_uri):
    """Return the default database handle for `mongo_uri` (lazy, process-wide pymongo client).

    The client is built once under a lock (double-checked) so concurrent first-requests under a
    threaded/multi-worker server don't each open a connection pool. ``serverSelectionTimeoutMS`` +
    ``connectTimeoutMS`` make a down/unreachable Mongo fail fast (~2s) so the routes' try/except degrades
    to 503 instead of stalling a sync worker for many seconds during an outage. Indexes
    are ensured best-effort on first connect — if Mongo isn't ready yet it's logged and skipped, never
    fatal (the app-level checks still hold).
    """
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                _client = MongoClient(mongo_uri, serverSelectionTimeoutMS=2000, connectTimeoutMS=2000)
                try:
                    ensure_indexes(_client.get_default_database())
                except Exception:
                    logger.warning("index creation deferred — Mongo not ready", exc_info=True)
                # Note: the $jsonSchema validators (ensure_schema) are NOT applied per-connect — collMod
                # takes a collection lock, so running it on every worker's boot is a needless storm. The
                # seed/provisioning step (db/seed.py) applies them once. Indexes are cheap, so they stay.
    return _client.get_default_database()


# ---- users (auth seam) ----
def get_user(db, username):
    """Return ``{"username", "password_hash", "email", "display_name"}`` for `username`, or None.

    ``username`` is the stable, unique internal handle every collection keys on; ``display_name`` is the
    (non-unique) name shown to people, defaulting to the handle for accounts created before display names
    existed. A doc missing ``password_hash`` (a partial/corrupt write, or a direct DB edit) is treated as
    "no user" so login fails closed rather than 500-ing on a KeyError.
    """
    doc = db.users.find_one({"username": username})
    if doc is None or "password_hash" not in doc:
        return None
    return {"username": doc["username"], "password_hash": doc["password_hash"],
            "email": doc.get("email"), "display_name": doc.get("display_name") or doc["username"]}


def create_user(db, username, password_hash, email=None, display_name=None):
    """Create the user if absent. Return True if created, False if the handle already exists.

    ``username`` is the unique internal HANDLE; ``display_name`` is the shown name (need not be unique),
    defaulting to the handle when omitted (seed/legacy callers). The upsert + unique index on
    ``users.username`` make this atomic: when two registrations of the same handle race, exactly one
    insert wins and the loser's upsert raises ``DuplicateKeyError`` — caught here and reported as False,
    honouring the contract under concurrency. ``email`` is stored when given (registration provides it).
    """
    doc = {"username": username, "password_hash": password_hash,
           "display_name": display_name if display_name is not None else username}
    if email is not None:
        doc["email"] = email
    try:
        result = db.users.update_one({"username": username}, {"$setOnInsert": doc}, upsert=True)
    except DuplicateKeyError:
        return False
    return result.upserted_id is not None


def get_user_by_email(db, email):
    """Return the username registered to `email`, or None (used by the password-reset request)."""
    doc = db.users.find_one({"email": email})
    return doc["username"] if doc and "password_hash" in doc else None


def update_password(db, username, password_hash):
    """Set a new password hash for `username`. Returns True if a user matched (else name unknown)."""
    return db.users.update_one({"username": username}, {"$set": {"password_hash": password_hash}}).matched_count > 0


def update_display_name(db, username, display_name):
    """Set a new (non-unique) display name for `username`. Returns True if a user matched.

    Only the shown name changes — the stable, unique internal handle every collection keys on is
    untouched, so ownership, DM addressing and history all survive a rename.
    """
    return db.users.update_one({"username": username}, {"$set": {"display_name": display_name}}).matched_count > 0


# ---- login OTP (2-step verification) — a transient challenge stored on the user doc ----
# The code is stored HASHED (never plaintext), with an absolute expiry and an attempt counter; all three
# are $unset by clear_otp once used/expired. They're unconstrained extra fields under the users
# $jsonSchema (like score/votes on posts), so no validator change is needed.
def set_otp(db, username, otp_hash, expires_at):
    """Store a fresh login-OTP challenge on the user (overwrites any prior one, resets attempts to 0).

    Returns True if a user matched. ``expires_at`` is absolute epoch seconds (the route computes it);
    keeping the clock in the route makes this seam trivially fakeable in unit tests.
    """
    return db.users.update_one(
        {"username": username},
        {"$set": {"otp_hash": otp_hash, "otp_expires_at": expires_at, "otp_attempts": 0}},
    ).matched_count > 0


def get_otp(db, username):
    """Return ``{"otp_hash", "expires_at", "attempts"}`` for the pending challenge, or None if none."""
    doc = db.users.find_one({"username": username})
    if not doc or "otp_hash" not in doc:
        return None
    return {"otp_hash": doc["otp_hash"], "expires_at": doc.get("otp_expires_at", 0),
            "attempts": doc.get("otp_attempts", 0)}


def clear_otp(db, username):
    """Remove the pending OTP challenge (after a success, an expiry, or a lockout)."""
    db.users.update_one({"username": username},
                        {"$unset": {"otp_hash": "", "otp_expires_at": "", "otp_attempts": ""}})


def bump_otp_attempts(db, username):
    """Atomically increment the failed-attempt counter; return the new count (0 if the challenge is gone).

    Atomic ``$inc`` (not read-modify-write) so two racing wrong guesses each observe a distinct
    post-increment value — neither can slip past the lockout by reading a stale pre-increment count.
    """
    doc = db.users.find_one_and_update(
        {"username": username, "otp_hash": {"$exists": True}},
        {"$inc": {"otp_attempts": 1}},
        return_document=ReturnDocument.AFTER,
    )
    return doc.get("otp_attempts", 0) if doc else 0


# ---- profiles (F2 seam) ----
def get_profile(db, username):
    """Return the stored profile dict for `username`, or None (also None if the row has no profile)."""
    doc = db.profiles.find_one({"username": username})
    return doc.get("profile") if doc else None


def save_profile(db, username, profile):
    """Upsert the user's profile (last write wins)."""
    db.profiles.update_one({"username": username}, {"$set": {"profile": profile}}, upsert=True)


# ---- history (F8 read + the check-in write) ----
def list_history(db, username):
    """Return the user's analysis-history entries (oldest-first; append-only natural order).

    Malformed rows without an ``entry`` field are skipped rather than raising, so one bad write can't
    500 the whole history view.
    """
    return [doc["entry"] for doc in db.analysis_history.find({"username": username}) if "entry" in doc]


def add_history(db, username, entry):
    """Append one analysis-history entry for the user (written by the daily check-in)."""
    db.analysis_history.insert_one({"username": username, "entry": entry})


# ---- forum (CRUD seam; the real-time push stays Elad's; the seed mechanism is db/seed.py) ----
def _comment_public(c):
    """Public projection of one comment — id/author/body/score, dropping the internal votes list."""
    return {"id": c.get("id"), "author": c.get("author"), "body": c.get("body"), "score": c.get("score", 0)}


def _shape(post):
    """Public projection of a forum post — drops the raw _id and the internal votes lists (post + comments)."""
    return {"id": post["id"], "author": post["author"], "anonymous": post.get("anonymous", False),
            "title": post["title"], "body": post["body"], "score": post.get("score", 0),
            "comments": [_comment_public(c) for c in post.get("comments", [])]}


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
    """Append a comment (with its own id + empty vote tally) and return its public shape, or None if
    the post is unknown. The id lets a comment be up/downvoted independently of its post."""
    comment = {"id": uuid.uuid4().hex, "author": author, "body": body, "votes": [], "score": 0}
    result = db.forum_posts.update_one({"id": post_id}, {"$push": {"comments": comment}})
    return _comment_public(comment) if result.matched_count else None


def forum_vote_comment(db, post_id, comment_id, username, value):
    """Record one vote per user on a comment (re-voting replaces) and return the comment's new score,
    or None if the post or comment is unknown.

    Same optimistic-concurrency guard as ``forum_vote``, but the CAS is on the post's ``comments``
    array: the write only lands if that array is unchanged since we read it, so two concurrent comment
    votes can't lose each other's update. A concurrent delete/edit that changes the array makes the
    loser retry on fresh state; sustained contention exhausts the retries and raises (route -> 503).
    Votes live as a LIST of ``{"user", "value"}`` on the comment (never a username-keyed dict — a
    username may contain ``.``/``$``, illegal as Mongo field names).
    """
    for _ in range(_VOTE_RETRIES):
        post = db.forum_posts.find_one({"id": post_id})
        if post is None:
            return None
        old_comments = post.get("comments", [])
        idx = next((i for i, c in enumerate(old_comments) if c.get("id") == comment_id), None)
        if idx is None:
            return None
        new_comments = [dict(c) for c in old_comments]          # copy so old_comments stays intact for the CAS filter
        target = new_comments[idx]
        votes = [v for v in target.get("votes", []) if v.get("user") != username]  # drop this user's prior vote
        votes.append({"user": username, "value": value})
        target["votes"], target["score"] = votes, sum(v["value"] for v in votes)
        result = db.forum_posts.update_one(
            {"id": post_id, "comments": old_comments},          # CAS: only if the comments array is unchanged
            {"$set": {"comments": new_comments}},
        )
        if result.matched_count:
            return target["score"]
    raise RuntimeError(f"forum_vote_comment: lost the update race on comment {comment_id} after retries")


def forum_vote(db, post_id, username, value):
    """Record one vote per user (re-voting replaces) and return the new score, or None if unknown.

    Votes are stored as a LIST of ``{"user", "value"}`` — never a dict keyed by username, since a
    username may contain ``.`` or ``$`` (the validator only bounds length), which are illegal/fragile
    as MongoDB field names.

    Concurrency: the read-rebuild-write is guarded by **optimistic concurrency control** — the write
    only lands if the post's ``votes`` array is unchanged since we read it (the array is in the update
    filter). Two simultaneous votes can't lose each other's update: the loser's filter misses and it
    retries on the fresh state. A concurrent *delete* makes the re-read return None -> None. Extreme
    sustained contention exhausts the retries and raises (the route degrades it to a 503).
    """
    for _ in range(_VOTE_RETRIES):
        post = db.forum_posts.find_one({"id": post_id})
        if post is None:
            return None
        old_votes = post.get("votes", [])
        new_votes = [v for v in old_votes if v.get("user") != username]   # drop this user's prior vote
        new_votes.append({"user": username, "value": value})
        score = sum(v["value"] for v in new_votes)
        result = db.forum_posts.update_one(
            {"id": post_id, "votes": old_votes},                          # CAS: only if votes unchanged
            {"$set": {"votes": new_votes, "score": score}},
        )
        if result.matched_count:
            return score
    raise RuntimeError(f"forum_vote: lost the update race on post {post_id} after retries")


# A post may only be edited/deleted by its real author (even for anonymous posts, where the displayed
# author is hidden). These return None if the post is unknown, FORBIDDEN if the caller isn't the author.
FORBIDDEN = "forbidden"


def forum_update_post(db, post_id, username, title, body):
    """Update a post's title/body iff `username` is its author. -> shaped post / None / FORBIDDEN."""
    post = db.forum_posts.find_one({"id": post_id})
    if post is None:
        return None
    if post.get("author") != username:
        return FORBIDDEN
    result = db.forum_posts.update_one({"id": post_id}, {"$set": {"title": title, "body": body}})
    if not result.matched_count:
        return None                       # concurrently deleted between the author check and the write
    post["title"], post["body"] = title, body
    return _shape(post)


def forum_delete_post(db, post_id, username):
    """Delete a post iff `username` is its author. -> True (deleted) / None / FORBIDDEN."""
    post = db.forum_posts.find_one({"id": post_id})
    if post is None:
        return None
    if post.get("author") != username:
        return FORBIDDEN
    db.forum_posts.delete_one({"id": post_id})
    return True


# ---- direct messages + notifications (the social layer's private channel + notification feed) ----
# Real-time = short-interval CLIENT polling of the notification list (no new deps / no worker-model
# change; SSE is the documented future upgrade). A "thread" between two users is simply the messages
# whose {sender, recipient} is exactly that pair, in either direction — matched on the real username
# fields, never a joined-string id, so two different pairs can NEVER collide (usernames may contain any
# character, including a delimiter). The route always passes the caller as one side, so a caller can only
# ever read a thread they are part of — that IS the DM-privacy guarantee. Inputs are type-validated first.

def _message_shape(m):
    return {"id": m["id"], "sender": m["sender"], "recipient": m["recipient"],
            "body": m["body"], "created_at": m["created_at"], "read": m.get("read", False)}


def message_send(db, sender, recipient, body):
    """Store a direct message and return its public shape."""
    msg = {"id": uuid.uuid4().hex, "sender": sender, "recipient": recipient, "body": body,
           "created_at": time.time(), "read": False}
    db.messages.insert_one(msg)
    return _message_shape(msg)


def message_list_conversation(db, user_a, user_b):
    """Every message exchanged between two users (either direction), oldest first."""
    msgs = (list(db.messages.find({"sender": user_a, "recipient": user_b}))
            + list(db.messages.find({"sender": user_b, "recipient": user_a})))
    return [_message_shape(m) for m in sorted(msgs, key=lambda m: m.get("created_at", 0))]


def message_list_conversations(db, user):
    """One summary row per peer the user has messaged with (latest body + unread count), newest first."""
    mine = list(db.messages.find({"sender": user})) + list(db.messages.find({"recipient": user}))
    convos = {}
    for m in sorted(mine, key=lambda m: m.get("created_at", 0)):
        peer = m["recipient"] if m["sender"] == user else m["sender"]
        row = convos.setdefault(peer, {"peer": peer, "last_message": "", "last_at": 0, "unread": 0})
        row["last_message"], row["last_at"] = m.get("body", ""), m.get("created_at", 0)
        if m["recipient"] == user and not m.get("read"):
            row["unread"] += 1
    return sorted(convos.values(), key=lambda c: c["last_at"], reverse=True)


def message_mark_read(db, user, peer):
    """Mark every message `user` RECEIVED from `peer` as read (opening the thread clears it)."""
    db.messages.update_many({"sender": peer, "recipient": user}, {"$set": {"read": True}})


def message_count_since(db, user, since):
    """How many messages `user` has sent at/after `since` (epoch secs) — the anti-spam counter."""
    return sum(1 for m in db.messages.find({"sender": user}) if m.get("created_at", 0) >= since)


def _notification_shape(n):
    return {"id": n["id"], "type": n["type"], "actor": n["actor"], "ref": n.get("ref"),
            "text": n["text"], "created_at": n["created_at"], "read": n.get("read", False)}


def notification_add(db, user, ntype, actor, ref, text):
    """Create a notification for `user` (the recipient) and return its public shape."""
    n = {"id": uuid.uuid4().hex, "user": user, "type": ntype, "actor": actor,
         "ref": ref, "text": text, "created_at": time.time(), "read": False}
    db.notifications.insert_one(n)
    return _notification_shape(n)


def notification_list(db, user, since=None):
    """The user's notifications, newest first; `since` (epoch secs) returns only newer ones (polling)."""
    items = list(db.notifications.find({"user": user}))
    if since is not None:
        items = [n for n in items if n.get("created_at", 0) > since]
    return [_notification_shape(n) for n in sorted(items, key=lambda n: n.get("created_at", 0), reverse=True)]


def notification_mark_read(db, user, ids=None):
    """Mark the user's notifications read — all of them when ids is None, or just `ids` if a list is
    given. An empty list means "mark these zero" -> a no-op (NOT "mark everything")."""
    target = set(ids) if ids is not None else None
    for n in db.notifications.find({"user": user}):
        if not n.get("read") and (target is None or n.get("id") in target):
            db.notifications.update_one({"id": n["id"]}, {"$set": {"read": True}})


# ---- account deletion (GDPR right to erasure) — remove a user + ALL their personal data ----
def delete_user(db, username):
    """Delete the user's identity record. Returns True if a row was removed."""
    return db.users.delete_one({"username": username}).deleted_count > 0


def delete_profile(db, username):
    """Delete the user's fitness profile (a no-op if there is none)."""
    db.profiles.delete_one({"username": username})


def delete_history(db, username):
    """Delete all of the user's analysis-history entries."""
    db.analysis_history.delete_many({"username": username})


def message_delete_for_user(db, username):
    """Delete every DM the user SENT or RECEIVED (erases both sides of their conversations)."""
    db.messages.delete_many({"$or": [{"sender": username}, {"recipient": username}]})


def notification_delete_for_user(db, username):
    """Delete the user's notification inbox AND any notification where they are the actor, so their
    handle isn't left referenced inside someone else's feed."""
    db.notifications.delete_many({"$or": [{"user": username}, {"actor": username}]})


def forum_purge_user(db, username):
    """Erase the user from the forum: delete the posts they authored, and strip their comments and
    votes out of everyone else's posts — recomputing the affected post/comment scores so the forum
    stays consistent for the remaining users."""
    db.forum_posts.delete_many({"author": username})
    for post in list(db.forum_posts.find()):
        kept_comments, changed = [], False
        for c in post.get("comments", []):
            if c.get("author") == username:
                changed = True                                   # drop the user's comment entirely
                continue
            cvotes = [v for v in c.get("votes", []) if v.get("user") != username]
            if len(cvotes) != len(c.get("votes", [])):
                c = {**c, "votes": cvotes, "score": sum(v["value"] for v in cvotes)}
                changed = True
            kept_comments.append(c)
        pvotes = [v for v in post.get("votes", []) if v.get("user") != username]
        if len(pvotes) != len(post.get("votes", [])):
            changed = True
        if changed:
            db.forum_posts.update_one(
                {"id": post["id"]},
                {"$set": {"comments": kept_comments, "votes": pvotes,
                          "score": sum(v["value"] for v in pvotes)}})
