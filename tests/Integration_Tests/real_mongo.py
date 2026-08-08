"""Shared setup for the real-Mongo integration fixtures. OWNER: Lior.

Both real-Mongo test files (``test_db_mongo.py``, ``test_seed_mongo.py``) connect to whatever database
``TEST_MONGO_URI`` names and **wipe** it before and after every test. Two things follow from that, and
both used to be restated per file — which is exactly how they drifted apart:

* **The collection list must be complete.** ``meta`` holds the forum revision counter that every forum
  mutation increments; the file that omitted it silently accumulated that counter across runs.
* **Nothing may wipe a database that is not a test database.** A mis-set variable — a typo, a copied
  command, a stale shell export — is all it takes, and the loss is silent and total: the tests pass
  either way, so nothing signals what just happened.

Kept in one place so neither rule can hold in one suite and not the other.
"""
import os

import pytest

# Every collection the app writes. `meta` is included because `web/services/db.py` bumps the forum
# revision counter there on every forum mutation — a suite that leaves it out cleans everything it
# touched except the one counter it kept incrementing.
COLLECTIONS = ("users", "profiles", "analysis_history", "forum_posts",
               "forum_comments", "messages", "notifications", "meta")

# A database these fixtures are allowed to wipe has to say so in its name. The app's database is
# `worksmarter`; CI and the compose test stack both use `worksmarter_test`.
TEST_DB_SUFFIX = "_test"


def resolve_test_db_name(uri):
    """The database `uri` names, once it has been proved safe to wipe.

    Raises ``RuntimeError`` when the name is missing or is not a test database. Refusing *before* a
    client is ever opened keeps the dangerous operation unreachable rather than merely unreached, and
    it makes this rule checkable without a server. The failure is loud on purpose — a quiet skip would
    read as "the real-Mongo tests ran" while a wipe of real data was one keystroke away.
    """
    from pymongo import uri_parser
    name = uri_parser.parse_uri(uri).get("database")
    if not name:
        raise RuntimeError(
            f"TEST_MONGO_URI must name a database, e.g. .../worksmarter{TEST_DB_SUFFIX} (got {uri!r})")
    if not name.endswith(TEST_DB_SUFFIX):
        raise RuntimeError(
            f"refusing to wipe {name!r}: the real-Mongo fixtures drop every collection they know about, "
            f"so TEST_MONGO_URI must name a database ending in {TEST_DB_SUFFIX!r}")
    return name


def connect_wipeable_db():
    """Open ``TEST_MONGO_URI`` and return ``(client, db)`` for a database that is safe to wipe.

    Skips when there is simply nothing to test against — no URI set, no reachable server — so the suite
    stays green on a machine without MongoDB. A URI that IS set but names a non-test database is a
    misconfiguration, not an absence, and raises instead (see `resolve_test_db_name`).
    """
    pytest.importorskip("pymongo")
    uri = os.environ.get("TEST_MONGO_URI")
    if not uri:
        pytest.skip("set TEST_MONGO_URI (with a /dbname) to run the real-Mongo integration tests")
    name = resolve_test_db_name(uri)                       # refuse a non-test database before connecting
    from pymongo import MongoClient
    from pymongo.errors import PyMongoError
    client = MongoClient(uri, serverSelectionTimeoutMS=1500)
    try:
        client.admin.command("ping")
    except PyMongoError:
        client.close()
        pytest.skip(f"no reachable MongoDB at {uri}")
    return client, client[name]


def wipe(db):
    """Drop every collection the app writes, so a test starts from — and leaves — a clean database."""
    for name in COLLECTIONS:
        db[name].drop()
