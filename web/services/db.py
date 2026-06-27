"""MongoDB access (pymongo). OWNER: Elad — schema + queries.

Validate/whitelist input types before queries (NoSQL-injection defense). Collections (docs/DESIGN.md §2):
users, profiles, programs, analysis_history. Use `pymongo` (in requirements.txt).
"""


def get_db(mongo_uri):
    """Return a pymongo database handle for `mongo_uri`. OWNER: implement."""
    raise NotImplementedError("db.get_db — connect to Mongo and return the database handle")
