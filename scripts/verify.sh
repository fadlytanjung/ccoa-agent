#!/usr/bin/env bash
# Everything CI runs, run locally, in the same order.
#
# The point is that a green run here means a green run on GitHub. Every check below is
# also a step in .github/workflows/ci.yml, and the two are meant to stay in step — if you
# add one, add it in both places.
#
# Usage:  ./scripts/verify.sh [--fast] [--containers]
#           --fast        skip the browser tests (they start real servers)
#           --containers  also build both images and verify them (needs Docker, ~2 min)
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

FAST=0
CONTAINERS=0
for arg in "$@"; do
  case "$arg" in
    --fast)       FAST=1 ;;
    --containers) CONTAINERS=1 ;;
    *) die "Unknown option: $arg" ;;
  esac
done

FAILED=()

# Run a check, remember whether it failed, and keep going. Stopping at the first failure
# means finding them one push at a time.
run() {
  local name="$1"; shift
  printf '\n%s──%s %s\n' "$C_DIM" "$C_RESET" "$name"
  if "$@"; then
    pass "$name"
  else
    fail "$name"
    FAILED+=("$name")
  fi
}

in_backend()  { (cd "$REPO_ROOT/backend" && "$@"); }
in_frontend() { (cd "$REPO_ROOT/frontend" && "$@"); }

step "Backend"
run "ruff"            in_backend uv run ruff check .
run "ruff format"     in_backend uv run ruff format --check .
run "mypy --strict"   in_backend uv run mypy app
run "pytest"          in_backend uv run pytest -q
run "no inline prompts" in_backend uv run python tools/check_no_inline_prompts.py
run "alembic check"   bash -c "cd '$REPO_ROOT/backend' && DATABASE_URL=\"sqlite+pysqlite:///\$(pwd)/data/app.db\" uv run alembic check"

step "Frontend"
run "typecheck"  in_frontend npx tsc -b --noEmit
run "eslint"     in_frontend npm run --silent lint
run "vitest"     in_frontend npx vitest run

if (( ! FAST )); then
  step "Browser"
  # Playwright starts its own backend and dev server; a stale one on either port makes
  # it test yesterday's code, so clear them first (see playwright.config.ts).
  for port in 8000 5173; do
    lsof -ti "tcp:$port" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
  done
  run "playwright" in_frontend npx playwright test
fi

if have terraform; then
  step "Terraform"
  run "terraform fmt"      bash -c "terraform -chdir='$REPO_ROOT/terraform' fmt -check -recursive"
  # `-backend=false` so this needs no AWS credentials and no state: it checks the
  # configuration, which is what a local gate can honestly check.
  run "terraform validate" bash -c "terraform -chdir='$REPO_ROOT/terraform' init -backend=false -input=false >/dev/null && terraform -chdir='$REPO_ROOT/terraform' validate"
else
  warn "terraform is not installed — skipping the infrastructure checks"
fi

step "Repository"
run "no account identifiers" python3 "$REPO_ROOT/tools/check_no_account_identifiers.py"
run "implementation status"  python3 "$REPO_ROOT/tools/check_implementation_status.py"

if (( CONTAINERS )); then
  step "Containers"
  if docker info >/dev/null 2>&1; then
    run "backend image"   bash -c "cd '$REPO_ROOT/backend' && docker build -q -t ccoa-backend:dev . >/dev/null"
    run "backend replication" bash -c "cd '$REPO_ROOT/backend' && ./docker/verify-replication.sh"
    run "frontend image"  bash -c "cd '$REPO_ROOT/frontend' && docker build -q -t ccoa-frontend:local . >/dev/null"
    run "frontend serving" bash -c "cd '$REPO_ROOT/frontend' && ./docker/verify-image.sh"
  else
    warn "Docker is not running — skipping the container checks"
  fi
fi

echo
if (( ${#FAILED[@]} )); then
  printf '%s%d check(s) failed:%s\n' "$C_RED" "${#FAILED[@]}" "$C_RESET"
  printf '  - %s\n' "${FAILED[@]}"
  exit 1
fi
printf '%sAll checks passed.%s\n' "$C_GREEN" "$C_RESET"
