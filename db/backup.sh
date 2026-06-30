#!/usr/bin/env bash
# Mongo backup + retention (mongodump). OWNER: Lior.
#
# Dumps the database to a timestamped gzip archive, then prunes archives older than RETENTION_DAYS.
# Run on a schedule (cron, or a CI scheduled job) against the prod Mongo. Restore with:
#   mongorestore --gzip --archive=<archive> --uri="$MONGO_URI"
#
# Usage:
#   MONGO_URI="mongodb://user:pass@db:27017/worksmarter?authSource=admin" \
#     BACKUP_DIR=/var/backups/worksmarter RETENTION_DAYS=7 ./db/backup.sh
set -euo pipefail

: "${MONGO_URI:?set MONGO_URI to the database to back up}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/worksmarter}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
archive="${BACKUP_DIR}/worksmarter-${stamp}.gz"

mkdir -p "$BACKUP_DIR"
mongodump --uri="$MONGO_URI" --gzip --archive="$archive"
echo "backup written: $archive"

# retention: drop archives older than RETENTION_DAYS
find "$BACKUP_DIR" -name 'worksmarter-*.gz' -type f -mtime "+${RETENTION_DAYS}" -delete
echo "pruned backups older than ${RETENTION_DAYS} day(s)"
