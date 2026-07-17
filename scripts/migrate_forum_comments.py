"""One-shot migration: move embedded forum comments into the ``forum_comments`` collection (#331). OWNER: Lior.

Idempotent — safe to run repeatedly. Loads the real ``db.py`` and calls ``migrate_embedded_comments``, which
for every post that still carries an embedded ``comments`` array inserts each comment into ``forum_comments``,
sets the post's ``comment_count``, and drops the embedded array. A post already migrated (no ``comments``
field) is skipped, so re-running does nothing.

Run against the deployed Mongo (note the trailing ``/dbname``):
    MONGO_URI="mongodb://localhost:27017/worksmarter" python scripts/migrate_forum_comments.py
(For an auth'd / in-network DB, run it on the compose network — see db/README.md.)
"""
import importlib.util
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("migrate_forum_comments")

ROOT = Path(__file__).resolve().parent.parent
DB_PY = ROOT / "web" / "services" / "db.py"


def _load_db():
    spec = importlib.util.spec_from_file_location("db", str(DB_PY))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def migrate(mongo_uri):
    """Ensure indexes (so the new ``forum_comments`` index exists) then migrate. Returns posts migrated."""
    from pymongo import MongoClient

    db_mod = _load_db()
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        db = client.get_default_database()
        db_mod.ensure_indexes(db)                       # make sure the (post_id, created_at) index is present
        migrated = db_mod.migrate_embedded_comments(db)
        logger.info("migrated %d post(s) with embedded comments into forum_comments", migrated)
        return migrated
    finally:
        client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    uri = os.environ.get("MONGO_URI")
    if not uri:
        sys.stderr.write("set MONGO_URI (with a /dbname), e.g. mongodb://localhost:27017/worksmarter\n")
        sys.exit(2)
    migrate(uri)
