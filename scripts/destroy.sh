#!/usr/bin/env bash
# Tear down the environment — docs/08 §3.1.
#
# `dev` is ephemeral by design: applied to work, destroyed afterwards. This is not a
# cost-saving afterthought, it is the operating model (ADR-004), and the infrastructure is
# written so that a destroy completes with no manual emptying first — ECR repositories set
# `force_delete`, the S3 bucket sets `force_destroy`, and every log group has finite
# retention.
#
# Usage:  ./scripts/destroy.sh [--env dev] [--yes]
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

ENVIRONMENT="dev"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENVIRONMENT="$2"; shift 2 ;;
    --yes) ASSUME_YES=1; shift ;;
    *) die "Unknown option: $1" ;;
  esac
done

require aws
require terraform
assert_not_root

REGION="${AWS_REGION:-ap-southeast-1}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"

terraform -chdir="$REPO_ROOT/terraform" init -reconfigure -input=false \
  -backend-config="bucket=ccoa-tfstate-${ACCOUNT_ID}" \
  -backend-config="key=${ENVIRONMENT}/terraform.tfstate" \
  -backend-config="region=${REGION}" >/dev/null

step "About to destroy '$ENVIRONMENT'"
warn "every resource in the Terraform state, including the Cognito pool and its users"
confirm "Destroy?" || die "Cancelled."

terraform -chdir="$REPO_ROOT/terraform" destroy -input=false \
  -var-file="envs/${ENVIRONMENT}.tfvars" \
  -var="backend_image_tag=destroy" -var="frontend_image_tag=destroy" \
  -auto-approve

echo
pass "destroyed"
note "the state bucket and the deploy role survive — they are bootstrap, not environment"
