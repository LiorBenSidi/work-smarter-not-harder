"""Real backup+restore verification for db/backup.sh (#602 item 3). OWNER: Elad.

The unit test (`test_backup_script.py`) only pins the script's guardrails — it exists, is executable, and
fails fast without `MONGO_URI`. It never runs a real `mongodump`, so **restore was unverified**: a backup
you cannot restore is the same as no backup. This exercises the whole cycle against a throwaway ``_test``
database — seed known data → `db/backup.sh` (mongodump) → wipe (simulate loss) → `mongorestore` → assert
the data came back intact — which is the assertion the §5.4 "Data loss" risk row was missing.

Skips cleanly wherever a piece is absent, so it never false-reds: no `pymongo` / no `TEST_MONGO_URI` /
no reachable server (via `real_mongo.connect_wipeable_db`), `mongodump`/`mongorestore` not on `PATH`
(the separate `mongodb-database-tools` — CI installs them; a bare machine skips), or Windows (``backup.sh``
runs under bash). It runs for real on Linux CI against the `mongo:7` service.
"""
import importlib.util
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from real_mongo import connect_wipeable_db, wipe

ROOT = Path(__file__).resolve().parents[2]
BACKUP_SH = ROOT / "db" / "backup.sh"
WEB = ROOT / "web"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="backup.sh runs under bash and needs mongodump/mongorestore; verified on Linux CI",
)


def _require_tools():
    for tool in ("mongodump", "mongorestore"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not on PATH — install mongodb-database-tools to run this test")


def _load_db():
    spec = importlib.util.spec_from_file_location("web_db_backup_it", str(WEB / "services" / "db.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _history_entry(day, sleep):
    return {"timestamp": f"2026-08-{day:02d}T06:00:00+00:00",
            "metrics": {"sleep_hours": sleep, "resting_hr": 55, "fatigue": 2, "soreness": 2, "training_load": 4},
            "assessment": "Ready", "proba": {"Ready": 0.8, "Moderate": 0.15, "Rest": 0.05},
            "calories": 2500, "recommendations": ["Readiness is high; proceed as planned."]}


def test_backup_then_restore_round_trips_the_data(tmp_path):
    """A real dump → wipe → restore cycle returns every seeded row, byte-for-byte in the fields that matter."""
    _require_tools()
    client, db = connect_wipeable_db()          # skips if no TEST_MONGO_URI / no server; refuses a non-_test db
    uri = os.environ["TEST_MONGO_URI"]           # guaranteed set once connect_wipeable_db() didn't skip
    dbm = _load_db()
    try:
        wipe(db)

        # --- seed known sentinel data through the real CRUD (real row shapes) ---
        assert dbm.create_user(db, "backup_alice", "hash-A",
                               email="alice@example.com", display_name="Alice B") is True
        for i in range(3):
            dbm.add_history(db, "backup_alice", _history_entry(20 + i, 7.0 + i))
        # a third collection, seeded directly, to prove the whole DB round-trips (not just what CRUD touches)
        db.forum_posts.insert_one({"id": "post-8F3K", "author": "backup_alice",
                                   "title": "Backup title", "body": "distinctive-body-8F3K", "score": 0})

        users_before = db.users.count_documents({})
        history_before = len(dbm.list_history(db, "backup_alice"))
        posts_before = db.forum_posts.count_documents({})
        assert users_before == 1 and history_before == 3 and posts_before == 1

        # --- back up (the real script) ---
        backup_dir = tmp_path / "backups"
        env = {**os.environ, "MONGO_URI": uri, "BACKUP_DIR": str(backup_dir), "RETENTION_DAYS": "9999"}
        r = subprocess.run(["bash", str(BACKUP_SH)], capture_output=True, text=True, env=env)
        assert r.returncode == 0, f"backup.sh failed:\n{r.stderr}\n{r.stdout}"
        archives = list(backup_dir.glob("worksmarter-*.gz"))
        assert len(archives) == 1, f"expected one archive, got {archives}"
        assert archives[0].stat().st_size > 0, "archive is empty"

        # --- simulate data loss, and PROVE it actually left (guards a false pass) ---
        wipe(db)
        assert db.users.count_documents({}) == 0
        assert len(dbm.list_history(db, "backup_alice")) == 0
        assert db.forum_posts.count_documents({}) == 0

        # --- restore from the archive ---
        rr = subprocess.run(["mongorestore", "--gzip", f"--archive={archives[0]}", f"--uri={uri}"],
                            capture_output=True, text=True)
        assert rr.returncode == 0, f"mongorestore failed:\n{rr.stderr}\n{rr.stdout}"

        # --- assert the data came back intact (the assertion the old test lacked) ---
        user = dbm.get_user(db, "backup_alice")
        assert user is not None
        assert user["email"] == "alice@example.com" and user["display_name"] == "Alice B"
        assert db.users.count_documents({}) == users_before
        assert len(dbm.list_history(db, "backup_alice")) == history_before
        post = db.forum_posts.find_one({"id": "post-8F3K"})
        assert post is not None and post["body"] == "distinctive-body-8F3K"   # distinctive value survived
    finally:
        wipe(db)
        client.close()


def test_retention_prune_deletes_archives_older_than_the_window(tmp_path):
    """The prune step drops archives past RETENTION_DAYS and keeps newer ones — filesystem only, no Mongo.

    Backdating an archive's mtime past the window and asserting it is gone catches a broken `find -mtime`
    (e.g. a dropped `+`, which would match the wrong side and delete *recent* backups instead of old ones)."""
    _require_tools()
    uri = os.environ.get("TEST_MONGO_URI")
    if not uri:
        pytest.skip("set TEST_MONGO_URI to run backup.sh (it dumps before pruning)")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    old = backup_dir / "worksmarter-20200101T000000Z.gz"       # a pre-existing old archive
    old.write_bytes(b"stale")
    stale_mtime = time.time() - 8 * 24 * 3600                  # 8 days old, past RETENTION_DAYS=7
    os.utime(old, (stale_mtime, stale_mtime))

    env = {**os.environ, "MONGO_URI": uri, "BACKUP_DIR": str(backup_dir), "RETENTION_DAYS": "7"}
    r = subprocess.run(["bash", str(BACKUP_SH)], capture_output=True, text=True, env=env)
    assert r.returncode == 0, f"backup.sh failed:\n{r.stderr}\n{r.stdout}"

    assert not old.exists(), "an archive older than RETENTION_DAYS should have been pruned"
    fresh = list(backup_dir.glob("worksmarter-*.gz"))
    assert len(fresh) == 1, f"the just-written backup should remain, got {fresh}"
