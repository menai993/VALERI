#!/usr/bin/env sh
# VALERI database restore (M14).
#
# Restores a pg_dump custom-format dump into a target database. This is
# DESTRUCTIVE (--clean drops existing objects first), so it requires an explicit
# confirmation argument:
#
#   sh restore.sh <dump-file> --yes
#
# Reads PGHOST, PGPORT, POSTGRES_USER, POSTGRES_PASSWORD from the environment and
# the target DB from POSTGRES_DB (override with TARGET_DB to restore elsewhere,
# e.g. a scratch DB for verification — see docs/RUNBOOK.md).
set -eu

DUMP_FILE="${1:-}"
CONFIRM="${2:-}"

if [ -z "$DUMP_FILE" ] || [ "$CONFIRM" != "--yes" ]; then
  echo "usage: sh restore.sh <dump-file> --yes" >&2
  echo "  (--yes is required because restore is DESTRUCTIVE: it drops existing objects)" >&2
  exit 2
fi
if [ ! -f "$DUMP_FILE" ]; then
  echo "[restore] dump file not found: $DUMP_FILE" >&2
  exit 1
fi

PGHOST="${PGHOST:-db}"
PGPORT="${PGPORT:-5432}"
USER="${POSTGRES_USER:?POSTGRES_USER must be set}"
DB="${TARGET_DB:-${POSTGRES_DB:?POSTGRES_DB or TARGET_DB must be set}}"

export PGPASSWORD="${POSTGRES_PASSWORD:-}"

echo "[restore] restoring $DUMP_FILE → $DB@$PGHOST:$PGPORT (DESTRUCTIVE)"
# --clean --if-exists: drop existing objects first; --no-owner: ignore dump roles.
pg_restore --clean --if-exists --no-owner --no-privileges \
  --host="$PGHOST" --port="$PGPORT" --username="$USER" --dbname="$DB" \
  "$DUMP_FILE"

echo "[restore] done — table counts:"
psql --host="$PGHOST" --port="$PGPORT" --username="$USER" --dbname="$DB" -t -c \
  "SELECT schemaname || '.' || relname || ' = ' || n_live_tup
   FROM pg_stat_user_tables WHERE n_live_tup > 0 ORDER BY 1;" || true

echo "[restore] complete"
