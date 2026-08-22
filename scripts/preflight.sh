#!/usr/bin/env bash
# Check that this machine can build, test, and deploy the project.
#
# Run this first after cloning. It reports every missing or too-old tool at once rather
# than failing on the first one, because discovering four prerequisites one command at a
# time is the slowest possible way to start.
#
# Usage:  ./scripts/preflight.sh [--deploy]
#           --deploy   also check the tools only a deployment needs
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

WANT_DEPLOY=0
[[ "${1:-}" == "--deploy" ]] && WANT_DEPLOY=1

MISSING=0

check() {
  local name="$1" min="${2:-}" version_cmd="${3:-}" hint="${4:-}"
  if ! have "$name"; then
    fail "$name is not installed. $hint"
    MISSING=$((MISSING + 1))
    return
  fi
  if [[ -z "$min" ]]; then
    pass "$name"
    return
  fi
  local found
  found="$(eval "$version_cmd" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1)"
  if [[ -z "$found" ]]; then
    warn "$name is installed but its version could not be read"
    return
  fi
  if version_at_least "$min" "$found"; then
    pass "$name $found (need >= $min)"
  else
    fail "$name $found is too old — need >= $min. $hint"
    MISSING=$((MISSING + 1))
  fi
}

step "Core tooling"
check uv     0.5  "uv --version"      "https://docs.astral.sh/uv/getting-started/installation/"
check node   22   "node --version"    "https://nodejs.org — 22 LTS or newer"
check npm    10   "npm --version"     "ships with Node"
check python3 3.12 "python3 --version" "3.12+, used by the repository checks"

step "Container tooling"
if have docker && docker info >/dev/null 2>&1; then
  pass "docker (daemon running)"
else
  # Only the container checks need it, so this is a warning during setup and an error
  # in the scripts that actually build an image.
  warn "docker is not running — needed for the image checks and for deployment"
fi

if (( WANT_DEPLOY )); then
  step "Deployment tooling"
  # 1.11 is the floor, not 1.9: native S3 state locking (`use_lockfile`) landed in 1.10
  # and `dynamodb_table` was deprecated in 1.11, which is what lets this project avoid
  # DynamoDB entirely (docs/08 §3.4).
  check terraform 1.11 "terraform version" "https://developer.hashicorp.com/terraform/install"
  check aws       2    "aws --version"     "https://aws.amazon.com/cli/"
  check jq        1.6  "jq --version"      "brew install jq"
  have gh && pass "gh (optional, for setting repository secrets)" || warn "gh not installed (optional)"
fi

step "Repository"
[[ -f "$REPO_ROOT/backend/.env" ]] \
  && pass "backend/.env exists" \
  || warn "backend/.env is missing — copy backend/.env.example and add a Gemini API key"

if [[ -f "$REPO_ROOT/backend/.env" ]] && grep -qE '^\s*GEMINI_API_KEY\s*=\s*\S' "$REPO_ROOT/backend/.env"; then
  pass "GEMINI_API_KEY is set"
else
  warn "GEMINI_API_KEY is not set — the app runs, but the agent cannot answer"
fi

echo
if (( MISSING )); then
  die "$MISSING prerequisite(s) missing. Install them and run this again." 1
fi
printf '%sReady.%s Next: ./scripts/dev.sh\n' "$C_GREEN" "$C_RESET"
