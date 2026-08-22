#!/usr/bin/env bash
# Verify the frontend image actually serves what docs/07 §3.9 and docs/10 §3.8 promise.
#
# This exists because every defect it checks for was, at some point, present in a green
# build. `docker build` succeeded, the layers were correct, the bundle was in the image —
# and the container either died on start or served pages with none of the security
# headers it claimed. None of it is visible without running the thing and looking at the
# bytes on the wire:
#
#   * a pidfile in a directory the non-root user cannot write is a hard start failure;
#   * an `add_header` inside a `location` silently discards every inherited one, so a CSP
#     declared at server level reaches no response at all;
#   * `expires` plus `add_header Cache-Control` emits two competing Cache-Control headers.
#
# Usage:  ./docker/verify-image.sh [image]
set -uo pipefail

IMAGE="${1:-ccoa-frontend:local}"
NAME=ccoa-frontend-check
PORT=18080
BASE="http://127.0.0.1:${PORT}"

pass() { printf '\033[32mPASS\033[0m %s\n' "$1"; }
fail() { printf '\033[31mFAIL\033[0m %s\n' "$1"; FAILURES=$((FAILURES + 1)); }
info() { printf '  ... %s\n' "$1"; }

FAILURES=0

# Match against a captured string, never `producer | grep -q` — under `pipefail` grep
# closes the pipe on its first match and the pipeline reports failure on success. Same
# reasoning as backend/docker/verify-replication.sh.
expect() {
  haystack="$1" needle="$2" description="$3"
  if grep -qi -- "$needle" <<<"$haystack"; then pass "$description"; else fail "$description"; fi
}

expect_eq() {
  actual="$1" wanted="$2" description="$3"
  if [[ "$actual" == "$wanted" ]]; then pass "$description"; else fail "$description (got '$actual', wanted '$wanted')"; fi
}

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1; }
trap cleanup EXIT
cleanup

info "starting $IMAGE"
docker run -d --name "$NAME" -p "${PORT}:8080" "$IMAGE" >/dev/null || {
  fail "container started"; exit 1
}

# A container that exits during startup is the failure mode this script was written for,
# so say so with its logs rather than letting every later assertion fail as a timeout.
for _ in $(seq 1 40); do
  sleep 0.5
  curl -sf -o /dev/null "${BASE}/healthz" && break
  [[ -z "$(docker ps -q -f name=$NAME)" ]] && {
    fail "container stayed up"
    docker logs "$NAME" 2>&1 | tail -5
    exit 1
  }
done

pass "container started and stayed up"

# --- it serves -------------------------------------------------------------------
expect_eq "$(curl -s "${BASE}/healthz")" "ok" "/healthz answers for the target group"
expect_eq "$(curl -s -o /dev/null -w '%{http_code}' "${BASE}/")" "200" "the SPA is served"
expect_eq "$(curl -s -o /dev/null -w '%{http_code}' "${BASE}/some/deep/route")" "200" \
  "a client-side route falls back to index.html"

asset="$(curl -s "${BASE}/" | grep -oE '/assets/[^"]+\.js' | head -1)"
[[ -n "$asset" ]] && pass "index.html references a hashed bundle" || fail "index.html references a hashed bundle"
expect_eq "$(curl -s -o /dev/null -w '%{http_code}' "${BASE}${asset}")" "200" "the bundle is present"
expect_eq "$(curl -s -o /dev/null -w '%{http_code}' "${BASE}/assets/absent.js")" "404" \
  "a missing asset 404s rather than falling back to the SPA"

# --- it serves securely ----------------------------------------------------------
# Checked on all three location blocks, because the inheritance rule that broke this
# applies per-location: passing on one says nothing about the others.
for path in "/" "$asset" "/healthz"; do
  headers="$(curl -sI "${BASE}${path}")"
  expect "$headers" "content-security-policy" "CSP is sent for ${path}"
  expect "$headers" "x-content-type-options: nosniff" "nosniff is sent for ${path}"
  expect "$headers" "x-frame-options: DENY" "X-Frame-Options is sent for ${path}"
  expect "$headers" "referrer-policy" "Referrer-Policy is sent for ${path}"
  expect "$headers" "permissions-policy" "Permissions-Policy is sent for ${path}"
done

expect "$(curl -sI "${BASE}/")" "connect-src 'self'" "the CSP allows same-origin API calls"

# The default must stay restrictive: an image started with no configuration should not
# be able to reach anything but itself.
expect_eq "$(curl -sI "${BASE}/" | grep -oiE "connect-src [^;]+" | tr -d "\r")" \
  "connect-src 'self'" "connect-src defaults to same-origin only"

# --- it caches correctly ---------------------------------------------------------
expect "$(curl -sI "${BASE}/")" "cache-control: no-store" "index.html is never cached"
asset_cc="$(curl -sI "${BASE}${asset}" | grep -ci '^cache-control')"
expect_eq "$asset_cc" "1" "the bundle carries exactly one Cache-Control"
expect "$(curl -sI "${BASE}${asset}")" "immutable" "the bundle is cached immutably"

# --- the CSP can be widened for the identity provider, and only for it -------------
#
# `connect-src 'self'` alone silently breaks sign-in: the PKCE token exchange is a
# browser fetch to Cognito, and the policy refuses it *after* the redirect has already
# succeeded. That shipped once. This asserts the substitution works, so a broken
# entrypoint cannot quietly restore the default.
info "restarting with CSP_CONNECT_SRC set"
docker rm -f "$NAME" >/dev/null 2>&1
docker run -d --name "$NAME" -p "${PORT}:8080" \
  -e "CSP_CONNECT_SRC='self' https://example.auth.ap-southeast-1.amazoncognito.com" \
  "$IMAGE" >/dev/null

for _ in $(seq 1 40); do sleep 0.5; curl -sf -o /dev/null "${BASE}/healthz" && break; done

csp="$(curl -sI "${BASE}/" | grep -oiE "connect-src [^;]+" | tr -d '\r')"
expect "$csp" "amazoncognito.com" "connect-src accepts a configured identity provider"
expect "$csp" "'self'" "...while still allowing same-origin"
expect_eq "$(grep -c 'amazonaws.com' <<<"$csp" || true)" "0" \
  "...and nothing that was not configured"

# --- it runs as it will on Fargate ------------------------------------------------
expect_eq "$(docker exec "$NAME" id -un)" "nginx" "nginx runs as a non-root user"
expect "$(docker inspect -f '{{.Config.ExposedPorts}}' "$IMAGE")" "8080" \
  "the image exposes 8080, so the task needs no added capabilities"
expect_eq "$(curl -sI "${BASE}/" | grep -ci '^server: nginx/')" "0" \
  "the server version is not advertised"

echo
if ((FAILURES)); then
  printf '\033[31m%d check(s) failed\033[0m\n' "$FAILURES"
  exit 1
fi
printf '\033[32mall checks passed\033[0m\n'
