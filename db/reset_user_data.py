"""Reset all USER DATA while keeping the user ACCOUNTS. OWNER: Lior.

Use this to get a clean slate for testing/demo WITHOUT losing any login. It empties every data
collection (profiles, check-in + AI history, forum, chat, notifications) but never touches ``users`` —
so every account (username / email / password_hash / display_name) survives and everyone can still log in.
That is why nothing has to be re-created afterwards.

Collections it CLEARS (``delete_many({})`` — keeps the collection, its validators and its indexes, just
removes every document):
    profiles           -- the user profile (age / gender / height / weight / goal / training days)
    analysis_history   -- daily check-ins AND the AI readiness predictions derived from them
    forum_posts        -- forum posts and their embedded comments  (incl. the cold-start seed posts)
    messages           -- direct messages / chat
    notifications       -- unread badges, vote pings, etc. (derived data)

Collections it KEEPS untouched:
    users              -- the login identities (username, password_hash, email, display_name, consent)

SAFETY: dry-run by default. It prints a before/after count table and deletes NOTHING unless you pass
``--apply``. It refuses to run without ``MONGO_URI``. It only ever clears the hard-coded data list above;
if it finds an unexpected collection it warns and leaves it alone (never a blind "drop everything").

Run (dry-run first, ALWAYS):
    MONGO_URI="mongodb://localhost:27017/worksmarter" python db/reset_user_data.py
Then, once the plan looks right, actually clear the data:
    MONGO_URI="mongodb://localhost:27017/worksmarter" python db/reset_user_data.py --apply
Optionally re-seed the cold-start forum posts afterwards (so the demo forum isn't an empty room):
    MONGO_URI="mongodb://localhost:27017/worksmarter" python db/reset_user_data.py --apply --reseed
(For the auth'd / in-network prod DB, run it on the compose network — see db/README.md.)
"""
import argparse
import logging
import os
import sys

logger = logging.getLogger("reset_user_data")

# The user DATA collections — every document in each is removed. `users` is deliberately NOT here.
DATA_COLLECTIONS = ["profiles", "analysis_history", "forum_posts", "messages", "notifications"]
# Never cleared. Listed explicitly so the report can PROVE the accounts were preserved.
KEEP_COLLECTIONS = ["users"]


def reset_user_data(db, apply=False):
    """Clear every DATA_COLLECTION; never touch KEEP_COLLECTIONS.

    Returns a report: {collection: {"before": n, "deleted": d, "after": a}} for the data collections,
    plus {collection: {"kept": n}} for the preserved ones. With ``apply=False`` (the default) it counts
    only and deletes nothing (``deleted`` is 0, ``after`` == ``before``) so a caller can preview the blast
    radius before committing.
    """
    report = {}
    for name in DATA_COLLECTIONS:
        coll = db[name]
        before = coll.count_documents({})
        deleted = 0
        if apply:
            deleted = coll.delete_many({}).deleted_count
        after = coll.count_documents({})
        report[name] = {"before": before, "deleted": deleted, "after": after}
    for name in KEEP_COLLECTIONS:
        report[name] = {"kept": db[name].count_documents({})}
    return report


def _warn_unexpected(db):
    """List collections that are neither data nor kept — so a new/unknown collection is never silently
    wiped OR silently assumed safe. Purely informational; nothing is done to them."""
    try:
        known = set(DATA_COLLECTIONS) | set(KEEP_COLLECTIONS)
        existing = set(db.list_collection_names())
        return sorted(existing - known)
    except Exception:                                     # list_collection_names can fail on restricted perms
        return []


def _print_report(report, unexpected, applied):
    mode = "APPLIED (data deleted)" if applied else "DRY-RUN (nothing deleted)"
    logger.info("\n  reset_user_data — %s", mode)
    logger.info("  %s", "-" * 52)
    logger.info("  %-20s%9s%9s%9s", "collection", "before", "deleted", "after")
    for name in DATA_COLLECTIONS:
        r = report[name]
        logger.info("  %-20s%9d%9d%9d", name, r["before"], r["deleted"], r["after"])
    logger.info("  %s", "-" * 52)
    for name in KEEP_COLLECTIONS:
        logger.info("  %-20s%9d   (KEPT — accounts preserved)", name, report[name]["kept"])
    if unexpected:
        logger.info("\n  ! unexpected collections left untouched: %s", ", ".join(unexpected))
    logger.info("")


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Clear all user DATA; keep user ACCOUNTS.")
    ap.add_argument("--apply", action="store_true", help="actually delete (default is a dry-run preview)")
    ap.add_argument("--reseed", action="store_true", help="after clearing, re-seed the cold-start forum posts")
    args = ap.parse_args(argv)

    mongo_uri = os.environ.get("MONGO_URI")
    if not mongo_uri:
        logger.error("ERROR: set MONGO_URI (e.g. mongodb://localhost:27017/worksmarter)")
        return 2

    from pymongo import MongoClient
    client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
    try:
        db = client.get_default_database()
        unexpected = _warn_unexpected(db)
        report = reset_user_data(db, apply=args.apply)
        _print_report(report, unexpected, applied=args.apply)
        if args.apply and args.reseed:
            # reuse the canonical seeder so re-seeded posts match user-created shape exactly
            import importlib.util
            from pathlib import Path
            seed_path = Path(__file__).resolve().parent / "seed.py"
            spec = importlib.util.spec_from_file_location("seed", str(seed_path))
            seed_mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(seed_mod)
            n = seed_mod.seed(mongo_uri)
            logger.info("  re-seeded %d starter forum posts\n", n)
        if not args.apply:
            logger.info("  (dry-run) re-run with --apply to actually clear the data above.\n")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
