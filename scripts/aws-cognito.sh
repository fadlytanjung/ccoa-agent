#!/usr/bin/env bash
# Create the Cognito user pool the SPA signs in against — docs/18 §7.
#
# Everything here is CLI. Nothing about Cognito genuinely requires the console, so nothing
# here asks you to open one; the console click-path in docs/18 §7.3 exists only for when a
# terminal is not available.
#
# Idempotent: run it twice and it finds what it already made rather than creating a second
# pool. Safe to re-run after a partial failure, which is the state you are actually in when
# you need it.
#
# It writes the three resulting values into backend/.env, because copying an id by hand is
# the step that goes wrong.
#
# **Nobody can sign themselves up.** `AllowAdminCreateUserOnly=true` is set explicitly,
# because Cognito's default is the opposite: leave it alone and anyone who finds the hosted
# UI can create an account, and every account they create can spend your model quota. Users
# are provisioned, never self-served — which is also what the requirements ask for
# (docs/10 §3.2).
#
# Usage:  ./scripts/aws-cognito.sh [--region ap-southeast-1] [--name ccoa-dev]
#                                  [--app-url https://xxxx.cloudfront.net] [--yes]
#         ./scripts/aws-cognito.sh --add-user someone@example.test [--group supervisor]
#         ./scripts/aws-cognito.sh --status
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

REGION="${AWS_REGION:-ap-southeast-1}"
POOL_NAME="ccoa-dev"
APP_URL=""
LOCAL_URL="http://localhost:5173"
ADD_USER=""
ADD_GROUP="agent"
ACTION="provision"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)   REGION="$2"; shift 2 ;;
    --name)     POOL_NAME="$2"; shift 2 ;;
    --app-url)  APP_URL="$2"; shift 2 ;;
    --add-user) ADD_USER="$2"; ACTION="add-user"; shift 2 ;;
    --group)    ADD_GROUP="$2"; shift 2 ;;
    --status)   ACTION="status"; shift ;;
    --yes)      ASSUME_YES=1; shift ;;
    *) die "Unknown option: $1" ;;
  esac
done

require aws
require jq
assert_not_root

aws_c() { aws --region "$REGION" "$@"; }

find_pool() {
  aws_c cognito-idp list-user-pools --max-results 60 \
    | jq -r --arg n "$POOL_NAME" '.UserPools[] | select(.Name == $n) | .Id' | head -1
}

# Provision one user. Split out so testers can be added later without re-running the whole
# script — which is the actual workflow, since a pool is created once and users are not.
add_user() {
  local pool_id="$1" email="$2" group="$3"
  if aws_c cognito-idp admin-get-user --user-pool-id "$pool_id" --username "$email" >/dev/null 2>&1; then
    pass "user exists"
  else
    aws_c cognito-idp admin-create-user \
      --user-pool-id "$pool_id" --username "$email" \
      --user-attributes Name=email,Value="$email" Name=email_verified,Value=true \
      --message-action SUPPRESS >/dev/null
    pass "created $email"
  fi

  aws_c cognito-idp admin-add-user-to-group \
    --user-pool-id "$pool_id" --username "$email" --group-name "$group" >/dev/null
  pass "in group '$group'"

  # Read from a prompt, never as an argument: a command line is visible in shell history
  # and in the process list, where any other process on this machine can read it.
  local password
  read -rs -p "    Password (12+ chars, upper, lower, digit): " password; echo
  [[ -n "$password" ]] || die "A password is required."

  # --permanent, or the user lands in FORCE_CHANGE_PASSWORD and the token exchange fails
  # with a message that says nothing about passwords.
  aws_c cognito-idp admin-set-user-password \
    --user-pool-id "$pool_id" --username "$email" \
    --password "$password" --permanent >/dev/null
  unset password
  pass "password set as permanent"
}

if [[ "$ACTION" == "add-user" ]]; then
  POOL_ID="$(find_pool)"
  [[ -n "$POOL_ID" ]] || die "No pool named '$POOL_NAME' in $REGION. Run without --add-user first."
  step "Adding $ADD_USER to $POOL_NAME"
  add_user "$POOL_ID" "$ADD_USER" "$ADD_GROUP"
  exit 0
fi

if [[ "$ACTION" == "status" ]]; then
  POOL_ID="$(find_pool)"
  [[ -n "$POOL_ID" ]] || die "No pool named '$POOL_NAME' in $REGION."
  step "Pool $POOL_NAME"
  SELF_SIGNUP="$(aws_c cognito-idp describe-user-pool --user-pool-id "$POOL_ID" \
    | jq -r '.UserPool.AdminCreateUserConfig.AllowAdminCreateUserOnly')"
  if [[ "$SELF_SIGNUP" == "true" ]]; then
    pass "self-registration is DISABLED — users are provisioned only"
  else
    fail "self-registration is ENABLED — anyone reaching the hosted UI can sign up"
    info "fix: re-run this script without --status"
  fi
  info "users:"
  aws_c cognito-idp list-users --user-pool-id "$POOL_ID" \
    --query 'Users[].{user:Username,status:UserStatus}' --output table
  exit 0
fi

step "User pool"
POOL_ID="$(find_pool)"

if [[ -n "$POOL_ID" ]]; then
  pass "reusing existing pool named $POOL_NAME"
else
  confirm "Create a Cognito user pool named '$POOL_NAME' in $REGION?" || die "Cancelled."
  POOL_ID="$(aws_c cognito-idp create-user-pool \
    --pool-name "$POOL_NAME" \
    --auto-verified-attributes email \
    --username-attributes email \
    --policies 'PasswordPolicy={MinimumLength=12,RequireUppercase=true,RequireLowercase=true,RequireNumbers=true,RequireSymbols=false}' \
    --admin-create-user-config 'AllowAdminCreateUserOnly=true' \
    --query 'UserPool.Id' --output text)"
  pass "created"
fi

# Applied on every run, not only at creation: a pool made before this flag existed — or by
# hand in the console — is still open to self-registration, and re-running the script is
# how someone would expect to close it.
aws_c cognito-idp update-user-pool --user-pool-id "$POOL_ID" \
  --admin-create-user-config 'AllowAdminCreateUserOnly=true' \
  --auto-verified-attributes email >/dev/null
pass "self-registration disabled — users are provisioned, never self-served"

step "Groups"
# Authorisation is by group claim, not by OAuth scope (docs/10 §3.3).
for group in agent supervisor; do
  if aws_c cognito-idp get-group --user-pool-id "$POOL_ID" --group-name "$group" >/dev/null 2>&1; then
    pass "$group exists"
  else
    aws_c cognito-idp create-group --user-pool-id "$POOL_ID" --group-name "$group" >/dev/null
    pass "$group created"
  fi
done

step "Hosted UI domain"
# The prefix is globally unique across all of AWS, so a fixed name collides for the second
# person who runs this. Derived from the pool id, which is already unique, with the region
# stripped out so nothing about the account ends up in a public repository (docs/18 §6).
DOMAIN_PREFIX="$(printf '%s' "$POOL_ID" | tr 'A-Z_' 'a-z-' | sed -E 's/^[a-z]+-[a-z]+-[0-9]+-//')"
DOMAIN_PREFIX="ccoa-${DOMAIN_PREFIX}"

EXISTING_DOMAIN="$(aws_c cognito-idp describe-user-pool --user-pool-id "$POOL_ID" \
  | jq -r '.UserPool.Domain // empty')"
if [[ -n "$EXISTING_DOMAIN" ]]; then
  DOMAIN_PREFIX="$EXISTING_DOMAIN"
  pass "reusing domain $DOMAIN_PREFIX"
else
  if aws_c cognito-idp create-user-pool-domain \
      --user-pool-id "$POOL_ID" --domain "$DOMAIN_PREFIX" >/dev/null 2>&1; then
    pass "created $DOMAIN_PREFIX"
  else
    die "Domain prefix '$DOMAIN_PREFIX' was rejected — most likely taken by another account.
    Pick your own:  aws cognito-idp create-user-pool-domain --user-pool-id $POOL_ID --domain <prefix> --region $REGION"
  fi
fi

step "App client"
CALLBACKS=("$LOCAL_URL/callback")
LOGOUTS=("$LOCAL_URL")
if [[ -n "$APP_URL" ]]; then
  CALLBACKS+=("${APP_URL%/}/callback")
  LOGOUTS+=("${APP_URL%/}")
fi

CLIENT_ID="$(aws_c cognito-idp list-user-pool-clients --user-pool-id "$POOL_ID" --max-results 60 \
  | jq -r '.UserPoolClients[] | select(.ClientName == "ccoa-spa") | .ClientId' | head -1)"

# `--no-generate-secret` is the load-bearing flag. A browser cannot keep a secret, and a
# confidential client fails at the token exchange — after a successful-looking sign-in,
# which makes it a genuinely confusing failure to diagnose.
CLIENT_ARGS=(
  --user-pool-id "$POOL_ID"
  --allowed-o-auth-flows code
  --allowed-o-auth-scopes openid email profile
  --allowed-o-auth-flows-user-pool-client
  --supported-identity-providers COGNITO
  --callback-urls "${CALLBACKS[@]}"
  --logout-urls "${LOGOUTS[@]}"
)

if [[ -n "$CLIENT_ID" ]]; then
  aws_c cognito-idp update-user-pool-client "${CLIENT_ARGS[@]}" \
    --client-id "$CLIENT_ID" --client-name ccoa-spa >/dev/null
  pass "updated (callbacks refreshed)"
else
  CLIENT_ID="$(aws_c cognito-idp create-user-pool-client "${CLIENT_ARGS[@]}" \
    --client-name ccoa-spa --no-generate-secret \
    --query 'UserPoolClient.ClientId' --output text)"
  pass "created"
fi
for url in "${CALLBACKS[@]}"; do note "callback: $url"; done

step "Writing backend/.env"
ENV_FILE="$REPO_ROOT/backend/.env"
[[ -f "$ENV_FILE" ]] || cp "$REPO_ROOT/backend/.env.example" "$ENV_FILE" 2>/dev/null || touch "$ENV_FILE"

set_env() {
  local key="$1" value="$2"
  if grep -qE "^\s*${key}\s*=" "$ENV_FILE"; then
    # A temp file and a move, not `sed -i`: the in-place flag differs between GNU and
    # BSD sed, and getting it wrong writes a stray backup file next to your secrets.
    awk -v k="$key" -v v="$value" \
      '$0 ~ "^[[:space:]]*"k"[[:space:]]*=" { print k"="v; next } { print }' \
      "$ENV_FILE" > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

set_env COGNITO_REGION "$REGION"
set_env COGNITO_USER_POOL_ID "$POOL_ID"
set_env COGNITO_CLIENT_ID "$CLIENT_ID"
set_env COGNITO_DOMAIN "$DOMAIN_PREFIX"
pass "pool, client, domain, and region written (the file is git-ignored)"

step "A user who can sign in"
# Creating a user needs a password typed at a prompt, so it is skipped entirely when
# running unattended. `--yes` means "do not ask me to confirm", not "answer prompts for
# me" — and auto-confirming here would hang on a `read` that no one is there to answer.
if [[ "${ASSUME_YES:-0}" == "1" ]] || [[ ! -t 0 ]]; then
  note "skipped (non-interactive) — add one with:"
  note "  ./scripts/aws-cognito.sh --add-user someone@example.test"
elif confirm "Create a sign-in user now?"; then
  read -r -p "    Email: " USER_EMAIL
  [[ -n "$USER_EMAIL" ]] || die "An email is required."
  add_user "$POOL_ID" "$USER_EMAIL" agent
else
  note "add one later:  ./scripts/aws-cognito.sh --add-user someone@example.test"
fi

echo
printf '%sDone.%s Sign in with:\n\n' "$C_GREEN" "$C_RESET"
printf '    ./scripts/dev.sh --cognito\n\n'
note "then open http://localhost:5173 — not 127.0.0.1, which is a different string to Cognito"
note "hosted UI: https://${DOMAIN_PREFIX}.auth.${REGION}.amazoncognito.com"
note "add more users:  ./scripts/aws-cognito.sh --add-user someone@example.test [--group supervisor]"
note "check the pool:  ./scripts/aws-cognito.sh --status"
