"""Seed MongoDB with indexes, validators, and cold-start forum content. OWNER: Lior.

Idempotent — safe to run repeatedly. Applies ``ensure_indexes`` + ``ensure_schema`` (so a fresh deploy
is fully provisioned), then inserts a small set of starter forum posts ONLY if the forum is empty (so a
brand-new deploy isn't an empty room — the rubric's "cold-seeding"). Reuses the real ``db.py`` CRUD, so
the seeded posts have exactly the same shape as user-created ones.

Run against the published dev Mongo:
    MONGO_URI="mongodb://localhost:27017/worksmarter" python db/seed.py
(For an auth'd / in-network DB, run it on the compose network — see db/README.md.)
"""
import importlib.util
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("seed")

ROOT = Path(__file__).resolve().parent.parent
DB_PY = ROOT / "web" / "services" / "db.py"

# (author, title, body) — placeholder starter content so a fresh forum isn't empty. Shiri's AI
# cold-seed generator can replace/augment this list with model-generated posts (her content lane).
SEED_POSTS = [
    ("coach_maya", "Welcome to the readiness forum 👋",
     "Share how training's going, ask for advice, compare readiness states. Be kind and specific."),
    ("coach_maya", "How to read your readiness state",
     "Ready = push. Moderate = steady. Rest = recover. It's a guide, not a rule — listen to your body too."),
    ("alex_runs", "Sleep vs readiness — same for you?",
     "Every time I drop under 6h sleep my readiness tanks the next day. Curious whether that's universal."),
]


def _load_db():
    spec = importlib.util.spec_from_file_location("db", str(DB_PY))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def seed(mongo_uri):
    """Provision (indexes + validators) and cold-seed the forum. Returns the number of posts inserted."""
    from pymongo import MongoClient

    db_mod = _load_db()
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        db = client.get_default_database()
        db_mod.ensure_indexes(db)
        db_mod.ensure_schema(db)
        logger.info("indexes + validators applied")
        if db.forum_posts.count_documents({}) == 0:
            for author, title, body in SEED_POSTS:
                db_mod.forum_create_post(db, author, title, body, False)
            logger.info("seeded %d starter forum posts", len(SEED_POSTS))
            return len(SEED_POSTS)
        logger.info("forum already has posts — skipping seed (idempotent)")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    uri = os.environ.get("MONGO_URI")
    if not uri:
        sys.stderr.write("set MONGO_URI (with a /dbname), e.g. mongodb://localhost:27017/worksmarter\n")
        sys.exit(2)
    seed(uri)
