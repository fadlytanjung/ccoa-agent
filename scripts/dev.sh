#!/usr/bin/env bash
# Run the whole application locally: backend on :8000, frontend on :5173.
#
# One command instead of two terminals, and it installs dependencies and seeds the
# database on first run so a fresh clone works without a checklist.
#
# Usage:  ./scripts/dev.sh [--cognito] [--reset]
#           --cognito  use a real Cognito pool instead of AUTH_MODE=dev (docs/18 §7)
#           --reset    clear conversation history before starting
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

AUTH_MODE=dev
RESET=0
for arg in "$@"; do
  case "$arg" in
    --cognito) AUTH_MODE=cognito ;;
    --reset)   RESET=1 ;;
    *) die "Unknown option: $arg" ;;
  esac
done

require uv
require node

# Kill both children when this script exits, however it exits. Without the trap, Ctrl-C
# leaves uvicorn holding :8000 and the next run fails with a port conflict that looks
# like something else entirely.
PIDS=()
cleanup() {
  for pid in "${PIDS[@]:-}"; do
    [[ -n "$pid" ]] && kill_tree "$pid"
  done
  wait 2>/dev/null || true

  # Belt and braces. If anything still holds a port after the tree walk, say so rather
  # than leaving the next run to discover it as a mystery.
  local stragglers
  stragglers="$(lsof -ti tcp:8000 -ti tcp:5173 2>/dev/null | tr '\n' ' ')"
  if [[ -n "${stragglers// /}" ]]; then
    warn "still holding a port: $stragglers — killing"
    # shellcheck disable=SC2086
    kill -9 $stragglers 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

step "Backend dependencies"
(cd "$REPO_ROOT/backend" && uv sync --quiet)
pass "installed"

if [[ ! -f "$REPO_ROOT/backend/data/app.db" ]]; then
  step "Seeding the database (first run)"
  (cd "$REPO_ROOT/backend" && uv run python -m app.seed --reset)
  pass "seeded"
fi

if (( RESET )); then
  step "Clearing conversation history"
  (cd "$REPO_ROOT/backend" && ASSUME_YES=1 uv run python tools/reset_conversations.py --tickets --yes)
fi

if [[ ! -d "$REPO_ROOT/frontend/node_modules" ]]; then
  step "Frontend dependencies (first run)"
  (cd "$REPO_ROOT/frontend" && npm ci --silent)
  pass "installed"
fi

if [[ "$AUTH_MODE" == "cognito" ]]; then
  step "Authentication: real Cognito pool"
  # Fail here rather than at the sign-in button. An unset pool renders an error screen
  # whose message is correct but arrives four steps later than it needed to.
  for var in COGNITO_USER_POOL_ID COGNITO_CLIENT_ID COGNITO_DOMAIN; do
    grep -qE "^\s*${var}\s*=\s*\S" "$REPO_ROOT/backend/.env" \
      || die "$var is not set in backend/.env. Run ./scripts/aws-cognito.sh, or see docs/18 §7."
  done
  pass "pool configured"
  note "sign in at http://localhost:5173 — not 127.0.0.1, unless that exact URL is a registered callback"
else
  step "Authentication: development bypass"
  note "AUTH_MODE=dev — no identity provider. Use --cognito for the real flow."
fi

step "Starting"
(
  cd "$REPO_ROOT/backend"
  ENVIRONMENT=local AUTH_MODE="$AUTH_MODE" \
    uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
) &
PIDS+=($!)

for _ in $(seq 1 60); do
  sleep 0.5
  curl -sf -o /dev/null http://127.0.0.1:8000/healthz && break
done
curl -sf -o /dev/null http://127.0.0.1:8000/healthz \
  || die "The backend did not become healthy. Check the output above."
pass "backend  http://127.0.0.1:8000  (docs at /docs)"

(cd "$REPO_ROOT/frontend" && npm run dev) &
PIDS+=($!)

for _ in $(seq 1 60); do
  sleep 0.5
  curl -sf -o /dev/null http://127.0.0.1:5173/ && break
done
pass "frontend http://localhost:5173"

echo
printf '%sRunning.%s Ctrl-C stops both.\n' "$C_GREEN" "$C_RESET"
wait
