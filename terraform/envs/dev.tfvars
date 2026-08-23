# The only environment ever applied — docs/08 §3.1.
#
# `dev` is full fidelity, not a stripped-down tier: it is what the requirements are
# evaluated against. It is also ephemeral — applied to work, destroyed afterwards.
environment = "dev"
region      = "ap-southeast-1"

# Both are overridden by the pipeline with the commit SHA. The placeholders are here so
# `terraform plan` runs locally without arguments; they are not valid images.
backend_image_tag  = "PLACEHOLDER"
frontend_image_tag = "PLACEHOLDER"

enable_langsmith   = false
log_retention_days = 7

# --- Edge -----------------------------------------------------------------------------
# --- Edge ---------------------------------------------------------------------------
# `alb`, not `cloudfront`. AWS will not create a distribution on an unverified account and
# that is a Support case with no API (docs/18 §3.4, ops-log.md).
#
# The brief leaves service selection open, so this is a choice rather than a compromise —
# but it is a real downgrade of one security boundary and docs/09 §6.6 says exactly which.
# Both branches run it, so that what is deployed is what is reviewed. Switching back is
# one word, once the account clears.
edge = "alb"

# Cognito rejects http:// callbacks for anything but localhost, so an unencrypted edge
# cannot sign anyone in at all. With no domain to get a real certificate for, this makes
# the environment usable at the cost of a browser warning on first visit. It expires in
# 30 days, so it cannot quietly become permanent.
# Set `domain_name` to a domain whose Route 53 zone you own and the browser warning goes
# away entirely: Terraform requests an ACM certificate, writes the DNS record that proves
# ownership, waits for validation, and points the domain at the load balancer. Until then
# the self-signed certificate keeps sign-in working, because Cognito rejects http://
# callbacks and an unencrypted edge cannot authenticate anyone at all.
domain_name             = ""
acm_certificate_arn     = ""
self_signed_certificate = true

# --- Cost ---------------------------------------------------------------------------
# Together these remove ~63% of the idle bill: ~$0.26/hour becomes ~$0.09/hour
# (docs/16 §4a). Both are availability and network-path trades, not capability ones —
# every requirement is still met, and each variable's description says exactly what is
# given up.
# Warm rather than scaled-to-zero. This environment is opened by people who are not its
# authors, and a 45-75 s cold start reads as "broken", not as "thrifty" (var.min_capacity).
min_capacity = 1

single_nat_gateway         = true
enable_interface_endpoints = false
