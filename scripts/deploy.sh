#!/usr/bin/env bash
# Deploy to AWS — docs/08 §3.8.
#
# The ordering matters and is not obvious, which is the main reason this is a script and
# not a paragraph in a runbook:
#
#   1. Create the ECR repositories first, on their own. Nothing can be pushed to a
#      repository that does not exist, and the services cannot start without images — so
#      a single `apply` would create ECS services that crash-loop on a missing image
#      while Terraform waits for them to stabilise, and then time out.
#   2. Build and push both images, tagged with the commit SHA. Never `latest`: it makes
#      rollback ambiguous and a redeploy non-reproducible (docs/08 §3.6).
#   3. Apply everything else, with those exact tags.
#   4. Put the secret values in place — never through Terraform, whose state would then
#      contain them (docs/10 §4).
#   5. Smoke-test what was actually deployed.
#
# Usage:  ./scripts/deploy.sh [--env dev] [--yes] [--plan-only]
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ENVIRONMENT="dev"
PLAN_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)       ENVIRONMENT="$2"; shift 2 ;;
    --yes)       ASSUME_YES=1; shift ;;
    --plan-only) PLAN_ONLY=1; shift ;;
    *) die "Unknown option: $1" ;;
  esac
done

# `prod` is configuration plus a pipeline job that is never approved (docs/00 §5). The
# guard is here as well as in the pipeline because a script is easier to run by accident
# than a gated job is to approve.
[[ "$ENVIRONMENT" == "dev" ]] || die "Only 'dev' is ever applied. See docs/00 §5 and ADR-006."

require aws
require terraform
require docker
require jq
assert_not_root

TF_DIR="$REPO_ROOT/terraform"
REGION="${AWS_REGION:-ap-southeast-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
TAG="$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD)"

# A dirty tree means the image would not correspond to any commit, so a rollback to "the
# previous tag" would restore something that never existed in git.
if ! git -C "$REPO_ROOT" diff --quiet HEAD 2>/dev/null; then
  warn "the working tree has uncommitted changes; image tag $TAG will not match its contents"
  confirm "Continue anyway?" || die "Cancelled."
fi

step "Plan"
info "environment: $ENVIRONMENT"
info "region:      $REGION"
info "image tag:   $TAG"

tf() {
  terraform -chdir="$TF_DIR" "$@"
}

step "Terraform init"
tf init -reconfigure -input=false \
  -backend-config="bucket=ccoa-tfstate-${ACCOUNT_ID}" \
  -backend-config="key=${ENVIRONMENT}/terraform.tfstate" \
  -backend-config="region=${REGION}" >/dev/null
pass "backend configured"

TF_ARGS=(-input=false -var-file="envs/${ENVIRONMENT}.tfvars"
  -var="backend_image_tag=${TAG}" -var="frontend_image_tag=${TAG}")

if (( PLAN_ONLY )); then
  step "Plan only"
  tf plan "${TF_ARGS[@]}"
  exit 0
fi

# --- 1. Repositories ------------------------------------------------------------------
step "1/5  ECR repositories"
tf apply "${TF_ARGS[@]}" -auto-approve \
  -target=aws_ecr_repository.backend \
  -target=aws_ecr_repository.frontend \
  -target=aws_ecr_lifecycle_policy.backend \
  -target=aws_ecr_lifecycle_policy.frontend >/dev/null
BACKEND_REPO="$(tf output -raw backend_ecr_repository)"
FRONTEND_REPO="$(tf output -raw frontend_ecr_repository)"
pass "ready"

# --- 2. Images ------------------------------------------------------------------------
step "2/5  Build and push"
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com" >/dev/null 2>&1
pass "authenticated to ECR"

# **linux/arm64**, matching the task definitions' `runtime_platform`. Building on an
# Apple Silicon machine gets this right by accident and on an Intel one gets it wrong the
# same way — the task then fails with `exec format error`, which names neither cause.
for service in backend frontend; do
  repo_var="$(tr '[:lower:]' '[:upper:]' <<<"$service")_REPO"
  repo="${!repo_var}"
  info "building $service for linux/arm64"
  docker build --platform linux/arm64 -t "${repo}:${TAG}" "$REPO_ROOT/$service" >/dev/null
  docker push "${repo}:${TAG}" >/dev/null
  pass "$service pushed as ${TAG}"
done

# --- 3. Everything else ----------------------------------------------------------------
step "3/5  Infrastructure"
if ! confirm "Apply the full stack to '$ENVIRONMENT'? This creates billable resources."; then
  die "Cancelled. The images are pushed; re-run to continue."
fi
tf apply "${TF_ARGS[@]}" -auto-approve
pass "applied"

APP_URL="$(tf output -raw app_url)"
POOL_ID="$(tf output -raw cognito_user_pool_id)"
CLIENT_ID="$(tf output -raw cognito_client_id)"

# --- 4. Secrets -------------------------------------------------------------------------
step "4/5  Secrets"
# Read from the local .env and written straight to Secrets Manager. Never through
# Terraform: a value set there lands in the state file, which is an S3 object that more
# people can read than should ever read an API key (docs/10 §4).
set_secret() {
  local name="$1" value="$2"
  if [[ -z "$value" ]]; then
    warn "$name is empty locally — skipping"
    return
  fi
  # `--secret-string file:///dev/stdin` keeps the value off the command line, where it
  # would be visible in shell history and in the process list.
  printf '%s' "$value" | aws secretsmanager put-secret-value \
    --secret-id "ccoa-${ENVIRONMENT}/${name}" \
    --secret-string file:///dev/stdin --region "$REGION" >/dev/null
  pass "$name set"
}

read_env() {
  # The first non-commented assignment wins. A commented-out duplicate above the real one
  # is exactly how a two-line value gets built by accident (see playwright.config.ts).
  grep -E "^\s*$1\s*=" "$REPO_ROOT/backend/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"' \r'
}

set_secret "gemini-api-key" "$(read_env GEMINI_API_KEY)"
set_secret "langsmith-api-key" "$(read_env LANGSMITH_API_KEY)"

# The tasks read secrets at start, so they have to be restarted now that the values exist.
for service in backend frontend; do
  aws ecs update-service --cluster "ccoa-${ENVIRONMENT}" \
    --service "ccoa-${ENVIRONMENT}-${service}" --force-new-deployment \
    --region "$REGION" >/dev/null
done
pass "services restarted to pick the secrets up"

# --- 5. Smoke test -----------------------------------------------------------------------
step "5/5  Smoke test"

# Bounded, and it polls rather than waiting on `aws ecs wait services-stable` — that
# waiter runs for up to 10 minutes before it gives up, which is far longer than anyone
# will watch and longer than the information is worth. A cold start is 45-75 s, so two
# minutes is generous; past that something is wrong and the logs are the next step, not
# more waiting.
SMOKE_TIMEOUT=150

code() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$1"; }

info "waiting for the first 200 (cold start is 45-75 s, cap ${SMOKE_TIMEOUT}s)"
deadline=$(( SECONDS + SMOKE_TIMEOUT ))
until [[ "$(code "$APP_URL/")" == "200" ]]; do
  if (( SECONDS >= deadline )); then
    fail "no 200 from $APP_URL within ${SMOKE_TIMEOUT}s"
    info "check:  aws logs tail /ecs/ccoa-${ENVIRONMENT}/backend --since 5m --region $REGION"
    info "        aws ecs describe-services --cluster ccoa-${ENVIRONMENT} \\"
    info "          --services ccoa-${ENVIRONMENT}-backend --region $REGION \\"
    info "          --query 'services[].events[:5]'"
    exit 1
  fi
  sleep 5
done
pass "responding after ${SECONDS}s"

check() {
  local description="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then pass "$description ($actual)"; else fail "$description — got $actual, wanted $expected"; fi
}

check "the SPA is served"          "200" "$(code "$APP_URL/")"
check "a client route falls back"  "200" "$(code "$APP_URL/threads/th_example")"
check "the API rejects anonymous"  "401" "$(code "$APP_URL/api/v1/threads")"
check "public config is readable"  "200" "$(code "$APP_URL/api/v1/config")"

# The highest-risk configuration in the whole design: a cached /api/* response would serve
# one agent's answer to another. Asserted, not assumed (docs/08 §3.5, docs/09 §8).
CACHE_HEADER="$(curl -s -D - -o /dev/null --max-time 30 "$APP_URL/api/v1/config" | grep -i '^x-cache' | tr -d '\r')"
if grep -qi 'miss' <<<"$CACHE_HEADER"; then
  pass "/api/* is not cached ($CACHE_HEADER)"
else
  fail "/api/* may be cached: $CACHE_HEADER"
fi

echo
printf '%sDeployed.%s\n\n' "$C_GREEN" "$C_RESET"
info "app:  $APP_URL"
note "add a user:  ./scripts/aws-cognito.sh --add-user someone@example.test"
note "tear down:   ./scripts/destroy.sh"
warn "dev is ephemeral — destroy it when you are done (docs/08 §3.1)."

# Keep the local SPA pointed at the same pool, so `dev.sh --cognito` and the deployed app
# authenticate against one identity provider rather than two.
info "local backend/.env now points at the deployed pool"
"$(dirname "${BASH_SOURCE[0]}")/aws-cognito.sh" --status >/dev/null 2>&1 || true
