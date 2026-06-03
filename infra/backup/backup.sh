#!/usr/bin/env sh
# VALERI database backup (M14).
#
# pg_dump in custom format (-Fc → compressed, restorable with pg_restore), then
# prune dumps older than the retention window. Usable two ways:
#   - manually:   sh backup.sh
#   - scheduled:  the `backup` compose service runs this daily (see docker-compose.yml)
#
# Reads from the environment (set by the compose service / .env):
#   PGHOST, PGPORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
#   BACKUP_DIR (default /backups), BACKUP_RETENTION_DAYS (default 14)
#
# On-prem note: copy the dumps off-host regularly (see docs/RUNBOOK.md) — a backup
# on the same machine does not survive that machine.
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
PGHOST="${PGHOST:-db}"
PGPORT="${PGPORT:-5432}"
DB="${POSTGRES_DB:?POSTGRES_DB must be set}"
USER="${POSTGRES_USER:?POSTGRES_USER must be set}"

mkdir -p "$BACKUP_DIR"
timestamp="$(date +%Y%m%d_%H%M%S)"
target="$BACKUP_DIR/valeri_${DB}_${timestamp}.dump"

export PGPASSWORD="${POSTGRES_PASSWORD:-}"

echo "[backup] dumping $DB@$PGHOST:$PGPORT → $target"
pg_dump --format=custom --no-owner --no-privileges \
  --host="$PGHOST" --port="$PGPORT" --username="$USER" --dbname="$DB" \
  --file="$target"

echo "[backup] done: $(du -h "$target" | cut -f1)"

# Prune old dumps (retention window).
echo "[backup] pruning dumps older than ${RETENTION_DAYS} days in $BACKUP_DIR"
find "$BACKUP_DIR" -name "valeri_*.dump" -type f -mtime "+${RETENTION_DAYS}" -print -delete || true

echo "[backup] complete"
