#!/usr/bin/env bash
# Create the things Terraform cannot create for itself — docs/18 §4.
#
# This is the chicken-and-egg layer: a state backend that must exist before
# `terraform init`, and the identity the pipeline assumes in order to run. Everything
# beyond this belongs to Terraform, and this script deliberately stops there.
#
# It creates:
#   1. an S3 bucket for Terraform state — versioned, encrypted, private, and locking
#      natively (no DynamoDB anywhere in this project — docs/08 §3.4);
#   2. the GitHub OIDC identity provider, so the pipeline needs no long-lived keys;
#   3. a permission boundary, and the `ccoa-deploy` role the pipeline assumes.
#
# Idempotent. Re-running finds what exists rather than failing, which matters because the
# first run of something like this rarely gets all the way through.
#
# Usage:  ./scripts/aws-bootstrap.sh --repo <ORG>/<REPO> [--region ap-southeast-1] [--yes]
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

REGION="${AWS_REGION:-ap-southeast-1}"
GITHUB_REPO=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)   GITHUB_REPO="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --yes)    ASSUME_YES=1; shift ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "$GITHUB_REPO" ]] || die "--repo <ORG>/<REPO> is required (the GitHub repository the pipeline runs from)."
[[ "$GITHUB_REPO" == */* ]] || die "--repo must be in the form <ORG>/<REPO>."

require aws
require jq
assert_not_root

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
BUCKET="ccoa-tfstate-${ACCOUNT_ID}"
BOUNDARY_NAME="ccoa-boundary"
ROLE_NAME="ccoa-deploy"
OIDC_HOST="token.actions.githubusercontent.com"

step "Plan"
info "region:      $REGION"
info "state bucket: ccoa-tfstate-<AWS_ACCOUNT_ID>"
info "deploy role:  $ROLE_NAME  (trusted from $GITHUB_REPO)"
confirm "Create these in this account?" || die "Cancelled."

# ---------------------------------------------------------------------------------
step "1/3  Terraform state bucket"

if aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null; then
  pass "bucket already exists"
else
  # us-east-1 rejects a LocationConstraint naming itself, which is the one special case
  # in an otherwise uniform API.
  if [[ "$REGION" == "us-east-1" ]]; then
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" >/dev/null
  else
    aws s3api create-bucket --bucket "$BUCKET" --region "$REGION" \
      --create-bucket-configuration LocationConstraint="$REGION" >/dev/null
  fi
  pass "created"
fi

# Versioning first: it is what makes a corrupted or truncated state recoverable, and it
# cannot be applied retroactively to objects written before it was enabled.
aws s3api put-bucket-versioning --bucket "$BUCKET" \
  --versioning-configuration Status=Enabled
pass "versioning enabled"

aws s3api put-bucket-encryption --bucket "$BUCKET" \
  --server-side-encryption-configuration \
  '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'
pass "encryption enabled"

# State holds resource attributes and occasionally secrets, so this bucket is sensitive
# even though it holds no application data.
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration \
  'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'
pass "public access blocked"

# ---------------------------------------------------------------------------------
step "2/3  GitHub OIDC provider"

OIDC_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/${OIDC_HOST}"
if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" >/dev/null 2>&1; then
  pass "provider already exists"
else
  # No thumbprint is passed. AWS stopped verifying it for its own trusted CAs, and a
  # pinned thumbprint became a scheduled outage for everyone who pinned one.
  aws iam create-open-id-connect-provider \
    --url "https://${OIDC_HOST}" \
    --client-id-list "sts.amazonaws.com" >/dev/null
  pass "created"
fi

# ---------------------------------------------------------------------------------
step "3/3  Permission boundary and deploy role"

BOUNDARY_ARN="arn:aws:iam::${ACCOUNT_ID}:policy/${BOUNDARY_NAME}"

# The document, once, so create and update cannot drift apart.
read -r -d '' BOUNDARY_DOC <<JSON || true
{
  "Version": "2012-10-17",
  "Statement": [
    { "Sid": "AllowServices", "Effect": "Allow", "Action": [
        "ec2:*", "ecs:*", "ecr:*", "elasticloadbalancing:*", "cloudfront:*",
        "logs:*", "s3:*", "secretsmanager:*", "cognito-idp:*", "wafv2:*",
        "application-autoscaling:*", "acm:*", "cloudwatch:*",
        "iam:PassRole", "iam:GetRole", "iam:CreateRole",
        "iam:DeleteRole", "iam:AttachRolePolicy", "iam:DetachRolePolicy",
        "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:TagRole", "iam:ListRolePolicies",
        "iam:ListAttachedRolePolicies", "iam:GetRolePolicy"
      ], "Resource": "*" },
    { "Sid": "NeverMintCredentials", "Effect": "Deny", "Action": [
        "iam:CreateUser", "iam:CreateAccessKey", "iam:CreateLoginProfile",
        "iam:DeleteUserPolicy", "iam:AttachUserPolicy",
        "organizations:*", "account:*"
      ], "Resource": "*" },
    { "Sid": "NeverEscapeTheBoundary", "Effect": "Deny", "Action": [
        "iam:DeletePolicy", "iam:DeletePolicyVersion", "iam:CreatePolicyVersion",
        "iam:SetDefaultPolicyVersion"
      ], "Resource": "${BOUNDARY_ARN}" }
  ]
}
JSON

if aws iam get-policy --policy-arn "$BOUNDARY_ARN" >/dev/null 2>&1; then
  # **Updated, not skipped.** A boundary is a ceiling: a role can be granted acm:* and
  # still be refused it if the boundary predates that service. That is exactly what
  # happened — the role policy was refreshed, the boundary was not, and the deploy failed
  # on `acm:DescribeCertificate` with a message about the role's identity policy.
  #
  # IAM keeps at most five versions, so the oldest non-default is pruned first.
  OLDEST="$(aws iam list-policy-versions --policy-arn "$BOUNDARY_ARN" \
    --query 'sort_by(Versions[?!IsDefaultVersion], &CreateDate)[0].VersionId' --output text)"
  if [[ "$(aws iam list-policy-versions --policy-arn "$BOUNDARY_ARN" --query 'length(Versions)' --output text)" -ge 5 ]]; then
    aws iam delete-policy-version --policy-arn "$BOUNDARY_ARN" --version-id "$OLDEST" >/dev/null
  fi
  aws iam create-policy-version --policy-arn "$BOUNDARY_ARN" \
    --policy-document "$BOUNDARY_DOC" --set-as-default >/dev/null
  pass "boundary updated"
else
  aws iam create-policy --policy-name "$BOUNDARY_NAME" --policy-document "$BOUNDARY_DOC" >/dev/null
  pass "boundary created"
fi

TRUST_POLICY="$(jq -n --arg arn "$OIDC_ARN" --arg host "$OIDC_HOST" --arg sub "$SUBJECT" '{
  Version: "2012-10-17",
  Statement: [{
    Effect: "Allow",
    Principal: { Federated: $arn },
    Action: "sts:AssumeRoleWithWebIdentity",
    Condition: {
      StringEquals: { ($host + ":aud"): "sts.amazonaws.com" },
      # Scoped to one repository. Without a `sub` condition any GitHub repository on
      # earth could assume this role — the single most common way this pattern is
      # misconfigured. See above for why the shape of this string matters.
      StringLike: { ($host + ":sub"): $sub }
    }
  }]
}')"

if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  aws iam update-assume-role-policy --role-name "$ROLE_NAME" \
    --policy-document "$TRUST_POLICY" >/dev/null
  pass "role exists — trust policy refreshed for $GITHUB_REPO"
else
  aws iam create-role --role-name "$ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --permissions-boundary "$BOUNDARY_ARN" \
    --description "GitHub Actions deploy role for CCOA. Managed by scripts/aws-bootstrap.sh." >/dev/null
  pass "created with the boundary attached"
fi

# ACM (the ALB certificate) and CloudWatch (the scale-from-zero alarms) were added to the
# infrastructure after this policy was first written, and the first pipeline deploy failed
# on `acm:DescribeCertificate`. A least-privilege policy is something to maintain, not
# something to write once — re-running this script is how it is brought back in line.
#
# The role's own permissions are the boundary's allow-list. The boundary is the ceiling;
# this is the grant. Both are needed — a boundary alone permits nothing.
aws iam put-role-policy --role-name "$ROLE_NAME" --policy-name ccoa-deploy-inline \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      { "Effect": "Allow", "Action": [
          "ec2:*", "ecs:*", "ecr:*", "elasticloadbalancing:*", "cloudfront:*",
          "logs:*", "secretsmanager:*", "cognito-idp:*", "wafv2:*",
          "application-autoscaling:*", "acm:*", "cloudwatch:*",
          "iam:PassRole", "iam:GetRole", "iam:CreateRole",
          "iam:DeleteRole", "iam:AttachRolePolicy", "iam:DetachRolePolicy",
          "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:TagRole",
          "iam:ListRolePolicies", "iam:ListAttachedRolePolicies", "iam:GetRolePolicy"
        ], "Resource": "*" },
      { "Effect": "Allow", "Action": "s3:*", "Resource": [
          "arn:aws:s3:::ccoa-*", "arn:aws:s3:::ccoa-*/*" ] }
    ]
  }' >/dev/null
pass "permissions attached"

ROLE_ARN="$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)"

# ---------------------------------------------------------------------------------
echo
printf '%sBootstrap complete.%s\n\n' "$C_GREEN" "$C_RESET"
info "Set the deploy role on the repository — the ARN contains the account id, so this"
info "goes in a GitHub secret and never in a file:"
echo
printf '    gh secret set AWS_DEPLOY_ROLE_ARN --repo %s --body "%s"\n' "$GITHUB_REPO" "$ROLE_ARN"
printf '    gh variable set AWS_REGION --repo %s --body "%s"\n' "$GITHUB_REPO" "$REGION"
echo
note "backend config for terraform/, once it exists:"
note "  bucket = \"ccoa-tfstate-<AWS_ACCOUNT_ID>\"   key = \"dev/terraform.tfstate\""
note "  region = \"$REGION\"                          use_lockfile = true"
echo
warn "Terraform itself is not implemented yet — docs/20 §4.4. This script sets up"
warn "everything it will need; there is nothing to apply until then."
