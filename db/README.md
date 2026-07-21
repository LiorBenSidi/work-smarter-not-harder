# `db` — the MongoDB container

The Mongo container is a **stock `mongo:7` image** (no custom build), defined in
[`../docker-compose.yml`](../docker-compose.yml): internal-only (no host port), a persistent named
volume (`mongo-data`), a `ping` healthcheck, and `restart: unless-stopped`. The app reaches it at
`MONGO_URI=mongodb://db:27017/worksmarter` (and `…/worksmarter_test` under the test stack).

## Provisioning — done (Lior)

The data-access layer is `web/services/db.py`. On first connect it applies, best-effort:

- **Indexes** (`ensure_indexes`) — unique `users.username`, `forum_posts.id`, `profiles.username`, plus a
  `analysis_history.username` performance index (so `list_history` is a per-user index scan, not a full scan).
- **Document-shape validators** (`ensure_schema`) — a `$jsonSchema` validator on all four collections, so
  the DB itself rejects a structurally-wrong document (defense-in-depth behind the route-layer validation).

### Seed (cold-start content)

`db/seed.py` applies the indexes + validators, creates a few **fake clients**, and seeds the forum with
**posts + comments (+ likes)** across a realistic recent timeline — **only if the forum is empty**
(idempotent; re-running creates nothing new). This is the Forum's cold-seeding sub-feature (rubric §7).

**It is a deliberate tool, not an auto-run:** a brand-new database is left **empty by design** (a real
deployment starts empty and fills with real users), so run this when you want a populated app — for the
demo, for local testing, or to give the TA a populated instance to review. Everything is written through
the real `web/services/db.py` CRUD, so seeded rows match user-created ones exactly. Against the published
dev Mongo:

```
MONGO_URI="mongodb://localhost:27017/worksmarter" python db/seed.py
```

The fake clients share a non-secret demo password (`demo-seed-pw`, override with `SEED_USER_PASSWORD`),
so you can log in as one and browse/post live during a demo. The starter text is a hand-written set;
Shiri's AI cold-seed generator can later augment it with model-generated content (her lane). For an
auth'd / in-network DB (no published port), run it on the compose network (a one-shot `python:3.12-slim`
container with `pymongo` + `werkzeug` and the repo mounted), or temporarily publish `27017`.

### Auth (env-gated)

Local dev runs **without** auth. To enable it, set `MONGO_USER` + `MONGO_PASSWORD` (the db container then
creates a root user and requires auth) and point `MONGO_URI` at the creds with `authSource=admin` — see
[`../.env.example`](../.env.example).

### Validate against a live instance

```
TEST_MONGO_URI="mongodb://localhost:27017/worksmarter_test" pytest tests/Integration_Tests/test_db_mongo.py
```

(CI also runs this real-Mongo suite on every PR via a `mongo:7` service — see `.github/workflows/ci.yml`.)

### Backups & retention

`db/backup.sh` (mongodump) dumps the database to a timestamped gzip archive and prunes archives older
than `RETENTION_DAYS`. Run it on a schedule against the prod Mongo; restore with `mongorestore`:

```
MONGO_URI="mongodb://user:pass@db:27017/worksmarter?authSource=admin" \
  BACKUP_DIR=/var/backups/worksmarter RETENTION_DAYS=7 ./db/backup.sh
# restore a chosen archive:
mongorestore --gzip --archive=worksmarter-<stamp>.gz --uri="$MONGO_URI"
```

`mongodump`/`mongorestore` ship with `mongo:7` (mongodb-database-tools), so the job can run from a
sidecar or the db host. The script fails fast if `MONGO_URI` is unset (covered by a unit test).

## Elad's adjacent pieces

- The **Azure deploy** that runs this `db` container as part of the live stack (keep it reachable at `MONGO_URI`).
- The Forum **real-time backbone** — WebSocket/SSE, notifications, DM transport, media/file store.
- **flask-limiter** rate-limiting on the public routes; **stress** + cross-container tests.
- The containerized **test-runner** in `docker-compose.test.yml` (runs `pytest` against the live stack).
