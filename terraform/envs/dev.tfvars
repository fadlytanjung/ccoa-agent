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
# The design docs/08 and docs/09 argue for: an internal ALB reachable only as a CloudFront
# VPC origin, with TLS from CloudFront's own certificate. The listener has no public
# address at all.
#
# **This branch cannot currently be applied.** AWS refuses to create a distribution on an
# unverified account (docs/18 §3.4, ops-log.md). The `develop` branch runs `edge = "alb"`
# instead and is what is deployed; switching back is this one word, once the account
# clears.
edge = "cloudfront"

# Unused under `edge = "cloudfront"` — CloudFront brings its own certificate.
acm_certificate_arn     = ""
self_signed_certificate = false

# --- Cost ---------------------------------------------------------------------------
# Together these remove ~63% of the idle bill: ~$0.26/hour becomes ~$0.09/hour
# (docs/16 §4a). Both are availability and network-path trades, not capability ones —
# every requirement is still met, and each variable's description says exactly what is
# given up.
single_nat_gateway         = true
enable_interface_endpoints = false
