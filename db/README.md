# `db` — the MongoDB container

The Mongo container is a **stock `mongo:7` image** (no custom build), defined in
[`../docker-compose.yml`](../docker-compose.yml): internal-only (no host port), a persistent named
volume (`mongo-data`), a `ping` healthcheck, and `restart: unless-stopped`. The app reaches it at
`MONGO_URI=mongodb://db:27017/worksmarter` (and `…/worksmarter_test` under the test stack).

## Initial container — ready
- Runs with `docker compose up --build` (no extra setup); the `worksmarter` DB is created on first write.
- The data-access layer is `web/services/db.py` (thin CRUD — Lior). The **unique constraints**
  (`users.username`, `forum_posts.id`) ship in `ensure_indexes()`, applied best-effort on first connect.
- Validate the CRUD against a live instance once it's up:
  `TEST_MONGO_URI="mongodb://localhost:27017/worksmarter_test" pytest tests/Integration_Tests/test_db_mongo.py`.

## Work WITHIN the DB — Elad
- **Auth** for production (`MONGO_INITDB_ROOT_USERNAME` / `MONGO_INITDB_ROOT_PASSWORD` + an auth'd
  `MONGO_URI`); the current open Mongo is fine only for the internal-only local/demo network.
- **Performance / schema indexes** beyond the unique ones, and any collection/schema design.
- **Seeding** (the Forum cold-start content) and any **backup / retention**.
- The containerized **test-runner** in `docker-compose.test.yml` (runs `pytest` against the live stack).
