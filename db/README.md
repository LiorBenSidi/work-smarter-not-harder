# `db` — the MongoDB container

The Mongo container is a **stock `mongo:7` image** (no custom build), defined in
[`../docker-compose.yml`](../docker-compose.yml): internal-only (no host port), a persistent named
volume (`mongo-data`), a `ping` healthcheck, and `restart: unless-stopped`. The app reaches it at
`MONGO_URI=mongodb://db:27017/worksmarter` (and `…/worksmarter_test` under the test stack).

## Provisioning — done (Lior)

The data-access layer is `web/services/db.py`.

- **Indexes** (`ensure_indexes`) — applied **best-effort on first connect**: unique `users.username`,
  `users.email` *(partial — only where the field exists)*, `forum_posts.id`, `forum_comments.id`,
  `profiles.username`; plus performance indexes — compound `analysis_history (username, entry.timestamp)`
  (so `list_history` is a per-user index scan, not a full scan), `forum_posts.created_at`,
  `forum_comments (post_id, created_at)`, `forum_posts.author` / `forum_comments.author`, the two
  `messages` thread indexes, and `notifications (user, created_at)`.
- **Document-shape validators** (`ensure_schema`) — **not** applied per-connect (`collMod` takes a collection
  lock, so running it on every worker boot would be a needless storm); the provisioning step `db/seed.py`
  applies them once. A `$jsonSchema` validator on six collections
  (`users`, `profiles`, `analysis_history`, `forum_posts`, `messages`, `notifications`), so the DB itself
  rejects a structurally-wrong document (defense-in-depth behind the route-layer validation).
  `forum_comments`, `meta` and `media` carry no validator.

### Seed (cold-start content)

`db/seed.py` applies the indexes + validators, then creates the whole demo population — **only if the
forum is empty** (idempotent; re-running creates nothing new). This covers the Forum's cold-seeding
sub-feature (rubric §7), and since #602 it covers the rest of the app too:

| What | How much |
|---|---|
| Fake clients | **15** athletes |
| Profiles | one each, spanning **beginner / intermediate / advanced** so every tier demos |
| Check-in history | up to **60 days** each, **scored by the real model** via `ai_client.predict` |
| Forum | **25** posts + **28** comments, votes, backdated across ~2 months |
| Direct messages | **7** threads, Hebrew and English, with a real unread tail |
| Notifications | derived from the seeded votes and DMs, exactly as the routes would raise them |
| Attachments | images + video on both posts and DMs, via `media_store`'s own contract |

The content itself lives in **`db/seed_content.py`** (data) — `seed.py` holds only the logic. History is
scored through the live `ai` container so a stored `assessment` always agrees with what the dashboard
shows for the same numbers; if `ai` is unreachable the seed falls back to a coarse offline rule **once**
and says so in its log.

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
Shiri's AI cold-seed generator can later augment it with model-generated content (her lane).

**`SEED_FORCE=1`** re-seeds a database that already holds forum content — the one case the idempotency
guard would otherwise make a silent no-op (re-seeding the prod box after purging test accounts). Leave it
unset everywhere else: a forced run on an already-seeded database **duplicates every post**, because post
ids are random and no unique index dedupes them.

#### Seed a running deployment (the demo / prod VM)

The `db` container is **internal** (no published port), so the one-liner above (which talks to a host
`localhost:27017`) can't reach it. Instead run the seed as a one-off container **on the compose network**,
reusing the `web` image (it already has `pymongo` + `werkzeug`) with the repo mounted:

```
MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' \
  docker compose run --rm -v "$PWD:/repo" -e MONGO_URI=mongodb://db:27017/worksmarter web python /repo/db/seed.py
```

The two `MSYS_*` vars matter **only on Windows/Git Bash**, where the shell rewrites both halves of
`"$PWD:/repo"` into Windows paths and the repo lands at `C:/repo` instead of `/repo` (#580). They are
unset and ignored on macOS/Linux, so the line is safe to paste anywhere.

Idempotent (a re-run prints "forum already has posts — skipping"). **Verified** end-to-end against a live
compose stack, 26 Aug: an empty database → 15 clients, 25 posts, 28 comments, 15 profiles, 539
model-scored check-ins, 31 messages, 91 notifications and 9 attachments, in under 10 seconds. This is the
command to run **once against the deployed VM before a demo / TA review**, so the live app shows a
populated app rather than a login screen.

Note it does **not** pass `-e MONGO_URI` when the deployment uses DB auth — `docker compose run web`
already inherits the service's own `MONGO_URI`, so overriding it with the no-auth form would fail there.
(If you *do* have a published Mongo port, the host `python db/seed.py` one-liner above is equivalent.)

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
