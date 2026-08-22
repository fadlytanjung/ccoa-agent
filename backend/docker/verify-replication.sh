#!/usr/bin/env bash
# Verify ADR-007 end to end, without provisioning anything in AWS.
#
#   write -> replicate -> destroy the container -> restore -> the write is still there
#
# This exists because the failure it catches is silent. A container that never restores
# still boots, still passes both health checks, and still answers correctly — it just
# serves the corpus baked in at build time, with none of the user's writes. Nothing in
# the logs says so. The only way to know is to kill the container and look.
#
# Runs against MinIO rather than S3: the S3 API surface Litestream uses is the same, and
# a test that needs a bucket, a role, and a region is a test nobody runs.
#
# Usage:  ./docker/verify-replication.sh [image]
set -uo pipefail

IMAGE="${1:-ccoa-backend:dev}"
NET=ccoa-replication-check
BUCKET=ccoa-replication-check
KEY=minioadmin
SECRET=minioadmin
APP_PORT=18001
MINIO_PORT=19000
APP_DB_PATH=/data/app.db

pass() { printf '\033[32mPASS\033[0m %s\n' "$1"; }
fail() { printf '\033[31mFAIL\033[0m %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
info() { printf '  ... %s\n' "$1"; }

FAILURES=0

# Match against a captured string, never `producer | grep -q`. Under `pipefail`, grep
# closes the pipe on its first match, the producer takes SIGPIPE, and the pipeline
# reports failure — so a passing assertion reads as a failing one. That bug cost a
# debugging round here; it does not get to happen twice.
expect() {
  haystack="$1" needle="$2" description="$3"
  if grep -q -- "$needle" <<<"$haystack"; then pass "$description"; else fail "$description"; fi
}

cleanup() {
  docker rm -f ccoa-replication-app ccoa-replication-minio >/dev/null 2>&1
  docker network rm "$NET" >/dev/null 2>&1
}
trap cleanup EXIT
cleanup
docker network create "$NET" >/dev/null 2>&1

mc() {
  docker run --rm --network "$NET" --entrypoint sh minio/mc:latest -c \
    "mc alias set m http://ccoa-replication-minio:9000 $KEY $SECRET >/dev/null && $1"
}

start_app() {
  docker run -d --name ccoa-replication-app --network "$NET" -p "$APP_PORT:8000" \
    -e ENVIRONMENT=local -e AUTH_MODE=dev -e GEMINI_API_KEY=probe-only \
    -e LITESTREAM_BUCKET="$BUCKET" \
    -e LITESTREAM_ENDPOINT="http://ccoa-replication-minio:9000" \
    -e AWS_REGION=us-east-1 \
    -e AWS_ACCESS_KEY_ID="$KEY" -e AWS_SECRET_ACCESS_KEY="$SECRET" \
    "$IMAGE" >/dev/null || return 1
  for _ in $(seq 1 40); do
    if [ "$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:$APP_PORT/healthz" 2>/dev/null)" = "200" ]; then
      return 0
    fi
    sleep 2
  done
  return 1
}

info "starting minio"
docker run -d --name ccoa-replication-minio --network "$NET" \
  -e MINIO_ROOT_USER=$KEY -e MINIO_ROOT_PASSWORD=$SECRET \
  -p "$MINIO_PORT:9000" minio/minio:latest server /data >/dev/null || {
  fail "could not start minio"; exit 1;
}
for _ in $(seq 1 30); do
  curl -sf "http://localhost:$MINIO_PORT/minio/health/live" >/dev/null 2>&1 && break
  sleep 2
done
mc "mc mb -p m/$BUCKET >/dev/null" || { fail "could not create the bucket"; exit 1; }

info "first boot — no replica yet, so the image's corpus should be used"
start_app || { fail "app did not become healthy"; docker logs ccoa-replication-app 2>&1 | tail -20; exit 1; }
expect "$(docker logs ccoa-replication-app 2>&1)" "using the image's copy" \
  "first boot falls through to the baked-in corpus"

info "writing through the API"
thread_id=$(curl -s -X POST "http://localhost:$APP_PORT/api/v1/threads" \
  -H 'content-type: application/json' -d '{"title":"replication check"}' |
  python3 -c 'import sys,json; print(json.load(sys.stdin)["thread_id"])') || {
  fail "could not create a thread"; exit 1;
}
sleep 5

objects="$(mc "mc ls -r m/$BUCKET")"
expect "$objects" "app.db/generations" "app.db is replicating"
expect "$objects" "checkpoints.db/generations" \
  "checkpoints.db is replicating — this is what makes a pending approval survive"

info "stopping with SIGTERM, as ECS scale-in does"
docker stop -t 60 ccoa-replication-app >/dev/null
expect "$(docker logs ccoa-replication-app 2>&1)" "litestream shut down" \
  "litestream owned the shutdown and completed its final sync"
docker rm -f ccoa-replication-app >/dev/null

info "second boot — a brand new container, which must restore"
start_app || { fail "app did not become healthy on the second boot"; exit 1; }
expect "$(docker logs ccoa-replication-app 2>&1)" "restored $APP_DB_PATH from the replica" \
  "second boot restored from the replica"

survived=$(curl -s "http://localhost:$APP_PORT/api/v1/threads" |
  python3 -c "import sys,json; print('yes' if any(r['thread_id']=='$thread_id' for r in json.load(sys.stdin)) else 'no')")
if [ "$survived" = "yes" ]; then
  pass "the write survived a container replacement — ADR-007 holds"
else
  fail "the write did not survive; durability is not working"
fi

echo
if [ "$FAILURES" -eq 0 ]; then
  printf '\033[32mreplication verified\033[0m\n'
else
  printf '\033[31m%d check(s) failed\033[0m\n' "$FAILURES"
fi
exit "$FAILURES"
