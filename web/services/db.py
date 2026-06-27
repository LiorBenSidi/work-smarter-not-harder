"""MongoDB access (pymongo). OWNER: Elad — schema + queries.

Baseline glue: `get_db` returns the default database handle (lazy connection). Validate/whitelist
input types before queries (NoSQL-injection defense). Collections (docs/DESIGN.md §2):
users, profiles, programs, analysis_history.
"""
from pymongo import MongoClient

_client = None


def get_db(mongo_uri):
    """Return the default database handle for `mongo_uri` (lazy pymongo connection)."""
    global _client
    if _client is None:
        _client = MongoClient(mongo_uri)
    return _client.get_default_database()
