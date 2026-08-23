#!/usr/bin/env bash
# Point the deployed environment at a domain you own, and get a certificate browsers trust.
#
# The self-signed certificate the environment ships with encrypts traffic but attests
# nothing, so every visitor is asked to override a warning. Only a certificate authority
# can fix that, and a CA issues for domains the requester can prove they control — which a
# load balancer's own `*.elb.amazonaws.com` name is not.
#
# Three things have to be true, and only the middle one needs a human:
#
#   1. a Route 53 hosted zone exists for the domain      — this script creates it
#   2. the registrar delegates to that zone's nameservers — you, at your registrar
#   3. `domain_name` is set in the environment's tfvars   — this script sets it
#
# Usage:  ./scripts/enable-domain.sh ccoa.example.com [--env dev]
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

DOMAIN="${1:-}"
ENVIRONMENT="dev"
WATCH=0
shift || true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)   ENVIRONMENT="$2"; shift 2 ;;
    --watch) WATCH=1; shift ;;
    *) die "Unknown option: $1" ;;
  esac
done

[[ -n "$DOMAIN" ]] || die "Usage: ./scripts/enable-domain.sh <domain> [--env dev]"

require aws
assert_not_root

TFVARS="$REPO_ROOT/terraform/envs/${ENVIRONMENT}.tfvars"
[[ -f "$TFVARS" ]] || die "No such environment: $TFVARS"

# The apex. `app.example.com` is served from the `example.com` zone.
APEX="$(awk -F. '{ if (NF>=2) print $(NF-1)"."$NF; else print $0 }' <<<"$DOMAIN")"

# --- 1. the hosted zone ---------------------------------------------------------------
step "Hosted zone for $APEX"
ZONE_ID="$(aws route53 list-hosted-zones-by-name --dns-name "$APEX" \
  --query "HostedZones[?Name=='${APEX}.'].Id | [0]" --output text 2>/dev/null || true)"

if [[ -z "$ZONE_ID" || "$ZONE_ID" == "None" ]]; then
  confirm "Create a public hosted zone for $APEX? (about \$0.50/month)" || die "Cancelled."
  ZONE_ID="$(aws route53 create-hosted-zone --name "$APEX" \
    --caller-reference "ccoa-$(date +%s)" \
    --hosted-zone-config Comment="CCOA — outlives any single environment" \
    --query 'HostedZone.Id' --output text)"
  pass "created"
else
  pass "already exists"
fi

# Deliberately **not** managed by Terraform. A zone recreated by `terraform destroy` gets
# new nameservers, which would mean editing the registrar again every time the ephemeral
# environment is torn down. Like the state bucket, the zone outlives the environment.
NS="$(aws route53 get-hosted-zone --id "$ZONE_ID" --query 'DelegationSet.NameServers' --output text | tr '\t' '\n')"

# --- 2. delegation, which only you can do ----------------------------------------------
#
# Asked of the **registry**, not of a public resolver. The two answer different questions,
# and only one of them is the truth:
#
#   * the TLD's nameservers hold the delegation itself — what your registrar has actually
#     published. This is authoritative and cannot be stale.
#   * 8.8.8.8 holds whatever it last cached, for as long as the previous record's TTL.
#
# Querying the resolver conflates "your registrar has not pushed the change yet" with
# "a resolver is still holding the old answer". Those need completely different responses:
# the first means wait or check the registrar, the second means only wait.

# `sed 's/\.$//'`: only the trailing root dot goes. `tr -d '.'` would flatten
# ns-612.awsdns-12.net into an unreadable run of letters.
nameservers_from() {
  nslookup -type=NS "$APEX" "$1" 2>/dev/null |
    awk -F'= ' '/nameserver/ { print $2 }' | sed 's/\.$//' | sort -u
}

check_delegation() {
  local tld registry resolver
  # The TLD's own servers, e.g. the `.site` registry.
  tld="$(nslookup -type=NS "${APEX##*.}." 8.8.8.8 2>/dev/null |
    awk -F'= ' '/nameserver/ { print $2 }' | sed 's/\.$//' | head -1)"

  registry=""
  [[ -n "$tld" ]] && registry="$(nameservers_from "$tld")"
  resolver="$(nameservers_from 8.8.8.8)"

  if grep -q 'awsdns' <<<"$registry"; then
    if grep -q 'awsdns' <<<"$resolver"; then
      DELEGATION_STATE="live"
    else
      # The registry has it; resolvers are still serving the old answer until its TTL
      # expires. ACM validates against authoritative servers, so this is already enough.
      DELEGATION_STATE="registry-only"
    fi
  else
    DELEGATION_STATE="pending"
  fi
  DELEGATION_REGISTRY="$registry"
  DELEGATION_RESOLVER="$resolver"
  DELEGATION_TLD="$tld"
}

report_pending() {
  echo
  info "The AWS zone is ready. What is missing is the delegation *at the registry*:"
  echo
  info "  registry (${DELEGATION_TLD:-unknown}) says: $(tr '\n' ' ' <<<"$DELEGATION_REGISTRY")"
  info "  public resolvers say:      $(tr '\n' ' ' <<<"$DELEGATION_RESOLVER")"
  echo
  info "Set these four at your registrar for ${APEX}, and save:"
  echo
  sed 's/^/      /' <<<"$NS"
  echo
  note "If they already show as saved there, the registrar has not yet published the"
  note "change to the registry. That is normally 15 minutes to a few hours, and there is"
  note "nothing to do but wait — this is registry data, not a cache anyone can flush."
  note "Watch for it with:  ./scripts/enable-domain.sh $DOMAIN --watch"
}

step "Delegation"
check_delegation

if (( WATCH )) && [[ "$DELEGATION_STATE" == "pending" ]]; then
  report_pending
  echo
  info "Watching — Ctrl-C to stop."
  while [[ "$DELEGATION_STATE" == "pending" ]]; do
    sleep 60
    check_delegation
    printf '    %s  registry: %s\n' "$(date +%H:%M:%S)" "$(tr '\n' ' ' <<<"$DELEGATION_REGISTRY")"
  done
  echo
fi

case "$DELEGATION_STATE" in
  live)
    pass "delegated to Route 53, and public resolvers agree"
    ;;
  registry-only)
    pass "delegated at the registry — enough for ACM, which asks authoritative servers"
    note "public resolvers still cache the old answer; that expires on its own"
    ;;
  *)
    fail "not delegated yet"
    report_pending
    exit 1
    ;;
esac

# --- 3. the variable --------------------------------------------------------------------
step "Configuration"
if grep -qE "^\s*domain_name\s*=\s*\"${DOMAIN}\"" "$TFVARS"; then
  pass "domain_name is already set"
else
  awk -v d="$DOMAIN" '
    $0 ~ /^[[:space:]]*domain_name[[:space:]]*=/ { print "domain_name             = \"" d "\""; found=1; next }
    { print }
    END { if (!found) print "domain_name             = \"" d "\"" }
  ' "$TFVARS" > "$TFVARS.tmp" && mv "$TFVARS.tmp" "$TFVARS"
  pass "domain_name set to $DOMAIN"
fi

echo
printf '%sReady.%s Commit and push to deploy:\n\n' "$C_GREEN" "$C_RESET"
printf '    git add terraform/envs/%s.tfvars\n' "$ENVIRONMENT"
printf '    git commit -m "infra: serve %s over TLS"\n' "$DOMAIN"
printf '    git push origin develop && git checkout main && git merge develop && git push origin main\n\n'
note "Terraform then requests the certificate, writes the DNS record that proves ownership,"
note "waits for validation, attaches it, and points $DOMAIN at the load balancer."
note "The self-signed certificate is dropped automatically, and Cognito's callback URLs follow."
