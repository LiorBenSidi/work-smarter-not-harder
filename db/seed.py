"""CLI to provision (indexes + validators) and cold-seed a MongoDB. OWNER: Lior.

The cold-seed CONTENT and the idempotent ``apply_seed`` live in ``web/seed_data.py`` — the single source
of truth, shared with the web container's on-boot seed (``wsgi.py`` → ``cold_seed_on_startup``). This CLI
is the manual path: point it at any Mongo and it applies the indexes, the ``$jsonSchema`` validators, and
the same seed content the running app would apply on startup. Idempotent: users are created only if
absent, forum content only if the forum is empty.

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
SEED_DATA_PY = ROOT / "web" / "seed_data.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Re-export the content + logic from web/seed_data.py so this module's public API — and the tests that
# load it — see SEED_* / apply_seed / DAY / SEED_PASSWORD in one place: the web tier's single source of truth.
_seed_data = _load("seed_data", SEED_DATA_PY)
SEED_PASSWORD = _seed_data.SEED_PASSWORD
DAY = _seed_data.DAY
SEED_USERS = _seed_data.SEED_USERS
SEED_POSTS = _seed_data.SEED_POSTS
SEED_COMMENTS = _seed_data.SEED_COMMENTS
SEED_POST_VOTES = _seed_data.SEED_POST_VOTES
SEED_COMMENT_VOTES = _seed_data.SEED_COMMENT_VOTES
apply_seed = _seed_data.apply_seed


def seed(mongo_uri):
    """Provision (indexes + validators) and cold-seed users + forum. Returns a {users, posts, comments} count."""
    from pymongo import MongoClient

    db_module = _load("db", DB_PY)
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        db = client.get_default_database()
        db_module.ensure_indexes(db)
        db_module.ensure_schema(db)
        logger.info("indexes + validators applied")
        result = apply_seed(db_module, db)
        logger.info("seed complete: %s", result)
        return result
    finally:
        client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    uri = os.environ.get("MONGO_URI")
    if not uri:
        sys.stderr.write("set MONGO_URI (with a /dbname), e.g. mongodb://localhost:27017/worksmarter\n")
        sys.exit(2)
    seed(uri)
