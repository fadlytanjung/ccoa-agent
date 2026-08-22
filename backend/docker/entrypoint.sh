#!/bin/sh
# Container entrypoint — ADR-007 §2.
#
# Boot order: restore from S3 (if a generation exists), migrate, then hand the process
# tree to Litestream so it is PID 1 and owns shutdown ordering.
set -eu

APP_DB="${DB_PATH:-/data/app.db}"
CHECKPOINT_DB="${CHECKPOINT_DB_PATH:-/data/checkpoints.db}"
PORT="${PORT:-8000}"

log() { printf '%s entrypoint: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

# The seed version is written at build time from the generator's own constant, so the
# S3 prefix cannot drift from the corpus it describes (docs/12 §3.6).
if [ -z "${SEED_VERSION:-}" ] && [ -r /data/SEED_VERSION ]; then
  SEED_VERSION="$(cat /data/SEED_VERSION)"
  export SEED_VERSION
fi
log "seed version ${SEED_VERSION:-unknown}"

# Without a bucket there is nothing to replicate to — that is the local and CI case,
# and it must still boot rather than failing on a missing variable.
if [ -z "${LITESTREAM_BUCKET:-}" ]; then
  log "LITESTREAM_BUCKET is unset; running without replication"
  alembic upgrade head
  exec uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
fi

# Restore whatever S3 holds for this seed version, preferring it over the copy baked
# into the image (ADR-007 §1a):
#
#   replica exists for this seed version -> restore it (it has the user's writes)
#   no replica                           -> keep the image's seeded database
#
# Restoring into a temporary file and swapping is what makes that choice safe. The
# obvious `-if-db-not-exists` does the wrong thing here: /data/app.db is *always*
# present because the build bakes it in, so that flag skips the restore on every boot
# and the task silently serves build-time data with none of the user's writes. Nothing
# fails, the health checks pass, and the durability guarantee is quietly void — which
# is exactly what the round-trip test in docs/08 §3.6 exists to catch.
restore_db() {
  db="$1"
  tmp="${db}.restored"
  rm -f "$tmp"

  if ! litestream restore -if-replica-exists -o "$tmp" -config /etc/litestream.yml "$db"; then
    log "restore FAILED for $db; continuing with the image's copy"
    rm -f "$tmp"
    return 0
  fi

  if [ -f "$tmp" ]; then
    # The -wal and -shm files belong to the copy being replaced; leaving them next to
    # a restored database is how you corrupt it.
    rm -f "${db}-wal" "${db}-shm"
    mv -f "$tmp" "$db"
    log "restored $db from the replica"
  else
    log "no replica for $db; using the image's copy"
  fi
}

for db in "$APP_DB" "$CHECKPOINT_DB"; do
  restore_db "$db"
done

log "applying migrations"
alembic upgrade head

log "starting under litestream"
# `-exec` makes Litestream PID 1: it forwards SIGTERM to uvicorn, waits for it, and
# performs a final sync before exiting. ECS `stopTimeout = 60` is what gives it room.
exec litestream replicate -config /etc/litestream.yml \
  -exec "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
