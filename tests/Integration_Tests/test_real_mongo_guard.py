"""Guards on the real-Mongo test fixtures themselves. OWNER: Lior.

Those fixtures WIPE a database, so two of their properties are worth proving rather than trusting: that
they refuse to wipe anything but a test database, and that the collection list they clean actually
covers what the app writes. Neither needs a running MongoDB, so these run everywhere the suite does —
including on the machines where every other real-Mongo test skips.
"""
import re
from pathlib import Path

import pytest
from real_mongo import COLLECTIONS, resolve_test_db_name

DB_PY = Path(__file__).resolve().parents[2] / "web" / "services" / "db.py"

# `db.<name>` uses inside db.py that are pymongo's own database API rather than a collection.
_DATABASE_API = {"command", "create_collection", "name", "client"}


@pytest.mark.parametrize("uri", [
    "mongodb://db:27017/worksmarter",                    # the app's own database
    "mongodb://localhost:27017/worksmarter",             # ...reached from the host instead
    "mongodb://db:27017/worksmarter_backup",             # a copy someone would very much like to keep
])
def test_the_real_mongo_fixtures_refuse_a_database_that_is_not_a_test_database(uri):
    """Pointing the test URI at real data must stop the run instead of quietly emptying it.

    The fixtures drop every collection they know about, and the tests pass either way, so a mis-set
    variable would destroy real data with nothing to signal it happened. The refusal has to come from
    the name alone — before a client is opened — because by the time anything is connected the only
    thing standing between the data and the drop is convention.
    """
    pytest.importorskip("pymongo")
    with pytest.raises(RuntimeError) as refusal:
        resolve_test_db_name(uri)
    assert "refusing to wipe" in str(refusal.value)


def test_a_uri_without_a_database_is_refused_rather_than_guessed():
    """A URI naming no database is a mistake worth stopping on, not something to resolve to a default.

    pymongo's default-database lookup returns nothing here, and continuing on a guess would put the
    wipe against whichever database the driver settled on.
    """
    pytest.importorskip("pymongo")
    with pytest.raises(RuntimeError) as refusal:
        resolve_test_db_name("mongodb://db:27017")
    assert "must name a database" in str(refusal.value)


@pytest.mark.parametrize("uri,expected", [
    ("mongodb://localhost:27017/worksmarter_test", "worksmarter_test"),            # CI + the compose test stack
    ("mongodb://localhost:27017/worksmarter_seed_test", "worksmarter_seed_test"),  # the cold-seed suite
])
def test_the_throwaway_databases_the_suite_actually_uses_are_accepted(uri, expected):
    """The databases CI and the documented commands really use must pass the guard.

    A rule that refuses everything would be just as broken as no rule at all — it would take the
    real-Mongo coverage offline while looking like a safety improvement.
    """
    pytest.importorskip("pymongo")
    assert resolve_test_db_name(uri) == expected


def test_every_collection_the_app_writes_is_one_the_fixtures_clean():
    """A collection the app writes but the fixtures never drop leaks state from one test run into the next.

    The expectation is read out of the data layer itself rather than restated here, so adding a
    collection to the app and forgetting the fixtures fails this instead of going unnoticed until
    something depends on a starting value.
    """
    used = {m for m in re.findall(r"\bdb\.([a-zA-Z_]+)", DB_PY.read_text()) if m not in _DATABASE_API}
    assert used <= set(COLLECTIONS), (
        f"the data layer writes {sorted(used - set(COLLECTIONS))}, which the real-Mongo fixtures never clean")
