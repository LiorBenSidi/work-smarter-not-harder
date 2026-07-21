"""Cold-seed content + logic, in the web tier so it ships in the web image. OWNER: Lior.

The rubric's cold-seeding (Forum §7): a fresh deploy comes up already populated — a few *fake* clients
with posts + comments (+ likes). This module holds the content and the idempotent ``apply_seed``; both
the web container (on startup, via ``cold_seed_on_startup`` in ``wsgi.py``) and the ``db/seed.py`` CLI
reuse it, so there is ONE source of truth for what gets seeded.

Idempotent: users are created only if the handle is absent, forum content only if the forum is empty —
so ``cold_seed_on_startup`` running on every boot is a cheap no-op after the first time, and it
self-heals if the DB volume is ever recreated (``docker compose down -v``).

``apply_seed(db_module, db)`` takes the db-layer module + a db handle, so it has no import-time
dependency on ``services.db`` — the CLI can load it against a path-loaded db module, and the web app
passes its own. The one heavier import here is werkzeug (present in both the web image and the CLI env),
needed because seeded accounts must carry a real hash so they can actually log in.
"""
import logging
import os
import time

from werkzeug.security import generate_password_hash

logger = logging.getLogger("seed")

DAY = 86_400  # seconds

# Fake clients get a shared, NON-SECRET demo password (throwaway seed accounts, never real people) so the
# forum can be browsed / posted-to live during a demo. Override with SEED_USER_PASSWORD.
SEED_PASSWORD = os.environ.get("SEED_USER_PASSWORD", "demo-seed-pw")

# (handle, display_name, email) — the unique handle is what posts/comments are authored by.
SEED_USERS = [
    ("coach_maya", "Coach Maya", "coach.maya@example.com"),
    ("alex_runs", "Alex", "alex.runs@example.com"),
    ("sara_lifts", "Sara", "sara.lifts@example.com"),
    ("deepa_yoga", "Deepa", "deepa.yoga@example.com"),
    ("tom_climbs", "Tom", "tom.climbs@example.com"),
]

# (author_handle, title, body, age_days) — age_days backdates created_at for a realistic timeline.
SEED_POSTS = [
    ("coach_maya", "Welcome to the readiness forum 👋",
     "Share how training's going, ask for advice, compare readiness states. Be kind and specific.", 14),
    ("coach_maya", "How to read your readiness state",
     "Ready = push. Moderate = steady. Rest = recover. It's a guide, not a rule — listen to your body too.", 12),
    ("alex_runs", "Sleep vs readiness — same for you?",
     "Every time I drop under 6h sleep my readiness tanks the next day. Curious whether that's universal.", 9),
    ("sara_lifts", "Deload weeks — how often do you take them?",
     "I've been running hard for 7 weeks straight and my numbers are stalling. Thinking it's deload time.", 6),
    ("deepa_yoga", "Mobility on rest days — worth it?",
     "On full-rest days I've started doing 20 min of mobility. My next session always feels smoother.", 3),
]

# (post_index, author_handle, body, age_days) — a comment can't predate its post, so keep age < the post's.
SEED_COMMENTS = [
    (0, "alex_runs", "Love this — thanks for setting it up!", 13),
    (0, "sara_lifts", "Finally a place to compare notes. 🙌", 13),
    (2, "coach_maya", "Very common — an under-6h night tanks most people's HRV the next morning.", 8),
    (2, "sara_lifts", "Same here, especially when training load is already high.", 8),
    (3, "deepa_yoga", "Every 4–6 weeks for me, and sooner if my sleep starts slipping.", 5),
    (4, "alex_runs", "20 minutes of mobility genuinely changes how my next session feels.", 2),
]

# Likes, so the forum isn't a flat wall of zero-score posts. (post_index, voter_handle).
SEED_POST_VOTES = [
    (0, "alex_runs"), (0, "sara_lifts"), (0, "deepa_yoga"), (0, "tom_climbs"),
    (2, "coach_maya"), (2, "sara_lifts"),
    (3, "alex_runs"), (3, "tom_climbs"),
    (4, "coach_maya"),
]
# (comment_index into SEED_COMMENTS, voter_handle).
SEED_COMMENT_VOTES = [
    (2, "alex_runs"), (2, "sara_lifts"), (4, "sara_lifts"), (5, "coach_maya"),
]


def _backdate(coll, doc_id, age_days):
    """Move a just-created row's ``created_at`` back by ``age_days`` (realistic timeline)."""
    coll.update_one({"id": doc_id}, {"$set": {"created_at": time.time() - age_days * DAY}})


def _seed_users(db_module, db):
    """Create the fake clients (idempotent — an existing handle is skipped). Returns how many were new."""
    password_hash = generate_password_hash(SEED_PASSWORD)
    created = 0
    for handle, display_name, email in SEED_USERS:
        if db_module.create_user(db, handle, password_hash, email=email, display_name=display_name):
            created += 1
    return created


def _seed_forum(db_module, db):
    """Insert posts + comments + likes, ONLY if the forum is empty. Returns {posts, comments} inserted."""
    # bounded existence check (never full-count a large forum). A SINGLE seeder is assumed: two concurrent
    # runs could both see an empty forum and double-seed (post ids are random, so the unique index won't
    # dedupe them) — fine for a one-shot init / a single-worker web boot.
    if db.forum_posts.count_documents({}, limit=1) != 0:
        logger.info("forum already has posts — skipping content seed (idempotent)")
        return {"posts": 0, "comments": 0}

    post_ids = []
    for author, title, body, age in SEED_POSTS:
        post = db_module.forum_create_post(db, author, title, body, False)
        _backdate(db.forum_posts, post["id"], age)
        post_ids.append(post["id"])

    comment_refs = []
    for post_index, author, body, age in SEED_COMMENTS:
        comment = db_module.forum_add_comment(db, post_ids[post_index], author, body)
        _backdate(db.forum_comments, comment["id"], age)
        comment_refs.append((post_ids[post_index], comment["id"]))

    for post_index, voter in SEED_POST_VOTES:
        db_module.forum_vote(db, post_ids[post_index], voter, 1)
    for comment_index, voter in SEED_COMMENT_VOTES:
        post_id, comment_id = comment_refs[comment_index]
        db_module.forum_vote_comment(db, post_id, comment_id, voter, 1)

    logger.info("seeded %d posts + %d comments (+ likes)", len(SEED_POSTS), len(SEED_COMMENTS))
    return {"posts": len(SEED_POSTS), "comments": len(SEED_COMMENTS)}


def apply_seed(db_module, db):
    """Create the fake clients, then the cold-start forum content. Returns a {users, posts, comments} count.

    Pure w.r.t. the db handle — runs against a real Mongo or an in-memory fake in tests."""
    users = _seed_users(db_module, db)
    forum = _seed_forum(db_module, db)
    return {"users": users, **forum}


def cold_seed_on_startup(app):
    """Best-effort cold-seed when the web container boots (called from wsgi.py, the real gunicorn process).

    Idempotent + non-fatal: it seeds when the forum is empty and no-ops otherwise, and ANY failure (Mongo
    not ready, a bug) is logged and swallowed — the user-facing container must always boot. Skipped under
    TESTING (the cross-container test-runner) and when COLD_SEED_ON_STARTUP=0."""
    if app.config.get("TESTING") or os.environ.get("COLD_SEED_ON_STARTUP", "1") == "0":
        return
    try:
        from services import db as db_module
        db = db_module.get_db(app.config["MONGO_URI"])   # also ensures indexes (best-effort) on first connect
        db_module.ensure_schema(db)
        result = apply_seed(db_module, db)
        if any(result.values()):
            logger.info("cold-seed applied on startup: %s", result)
    except Exception:
        logger.warning("cold-seed on startup skipped (non-fatal) — the app boots regardless", exc_info=True)
