#!/usr/bin/env sh
# VALERI backup restore-verification (P2).
#
# A backup that was never restored is a hope, not a backup. Weekly (see
# docker-compose.yml) this script takes the NEWEST dump, checks its sha256,
# restores it into a scratch database, sanity-checks the contents, drops the
# scratch DB, and records the outcome in app.job_run('backup_restore_check')
# on the MAIN database — which feeds /api/health alerts and the owner's bell
# ("backup_unverified" when this hasn't succeeded recently).
#
# Reads from the environment (set by the compose service / .env):
#   PGHOST, PGPORT, POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB
#   BACKUP_DIR (default /backups), SCRATCH_DB (default valeri_restore_check)
set -u

BACKUP_DIR="${BACKUP_DIR:-/backups}"
PGHOST="${PGHOST:-db}"
PGPORT="${PGPORT:-5432}"
USER="${POSTGRES_USER:?POSTGRES_USER must be set}"
MAIN_DB="${POSTGRES_DB:?POSTGRES_DB must be set}"
SCRATCH_DB="${SCRATCH_DB:-valeri_restore_check}"

export PGPASSWORD="${POSTGRES_PASSWORD:-}"

psql_main() {
  psql --host="$PGHOST" --port="$PGPORT" --username="$USER" --dbname="$MAIN_DB" "$@"
}

record() { # $1=status $2=error-or-empty $3=detail-json
  psql_main -q -v status="$1" -v err="$2" -v detail="$3" -c \
    "INSERT INTO app.job_run (job, status, finished_at, error, detail)
     VALUES ('backup_restore_check', :'status', now(), NULLIF(:'err',''), :'detail'::jsonb)" \
    || echo "[verify] WARNING: could not record job_run row" >&2
}

fail() { # $1=reason
  echo "[verify] FAILED: $1" >&2
  record failed "$1" '{}'
  dropdb --if-exists --host="$PGHOST" --port="$PGPORT" --username="$USER" "$SCRATCH_DB" 2>/dev/null || true
  exit 1
}

# 1. Newest dump.
newest="$(ls -1t "$BACKUP_DIR"/valeri_*.dump 2>/dev/null | head -1 || true)"
[ -n "$newest" ] || fail "no dumps found in $BACKUP_DIR"
echo "[verify] newest dump: $newest"

# 2. Checksum (when recorded — dumps predating P2 may not have one).
if [ -f "$newest.sha256" ]; then
  (cd "$BACKUP_DIR" && sha256sum -c "$(basename "$newest").sha256" >/dev/null 2>&1) \
    || fail "sha256 mismatch for $(basename "$newest")"
  echo "[verify] sha256 ok"
else
  echo "[verify] no .sha256 next to the dump — skipping checksum"
fi

# 3. Restore into a fresh scratch DB (never the live one).
dropdb --if-exists --host="$PGHOST" --port="$PGPORT" --username="$USER" "$SCRATCH_DB" \
  || fail "could not drop old scratch db"
createdb --host="$PGHOST" --port="$PGPORT" --username="$USER" "$SCRATCH_DB" \
  || fail "could not create scratch db"
pg_restore --no-owner --no-privileges \
  --host="$PGHOST" --port="$PGPORT" --username="$USER" --dbname="$SCRATCH_DB" "$newest" \
  || fail "pg_restore into $SCRATCH_DB failed"

# 4. Sanity: the schema came back and the business data is queryable.
tables="$(psql --host="$PGHOST" --port="$PGPORT" --username="$USER" --dbname="$SCRATCH_DB" -t -A -c \
  "SELECT count(*) FROM information_schema.tables
   WHERE table_schema IN ('core','app','audit','staging')" || echo "")"
[ -n "$tables" ] && [ "$tables" -ge 10 ] || fail "restored schema looks wrong (tables=$tables)"
invoice_rows="$(psql --host="$PGHOST" --port="$PGPORT" --username="$USER" --dbname="$SCRATCH_DB" -t -A -c \
  "SELECT count(*) FROM core.invoice" || echo "")"
[ -n "$invoice_rows" ] || fail "core.invoice not queryable in the restored copy"
echo "[verify] sanity ok: $tables tables, $invoice_rows invoices"

# 5. Clean up + record success.
dropdb --if-exists --host="$PGHOST" --port="$PGPORT" --username="$USER" "$SCRATCH_DB" || true
record ok "" "{\"dump\":\"$(basename "$newest")\",\"tables\":$tables,\"invoice_rows\":$invoice_rows}"
echo "[verify] complete — recorded backup_restore_check=ok"
