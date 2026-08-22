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
# `alb`, not `cloudfront`, because AWS will not create a distribution on an unverified
# account and that is a Support case with no API (docs/18 §3.4, ops-log.md).
#
# The brief leaves service selection open, so this is a choice rather than a compromise —
# but it is a real downgrade of one security boundary and docs/09 §6.6 says which. Switch
# back with a single word once the account clears.
edge = "alb"

# No certificate, so the viewer hop is HTTP. A certificate needs a domain, and an ALB's
# own *.elb.amazonaws.com name cannot have one. Set this and the listener serves HTTPS on
# 443 and redirects 80 to it — nothing else changes.
acm_certificate_arn = ""

# Cognito rejects http:// callbacks for anything but localhost, so an unencrypted edge
# cannot sign anyone in. With no domain to get a real certificate for, this is what makes
# the environment usable — at the cost of a browser warning on every first visit.
# Replace it with a real certificate as soon as there is a domain.
self_signed_certificate = true

# --- Cost ---------------------------------------------------------------------------
# Together these remove ~63% of the idle bill: ~$0.26/hour becomes ~$0.09/hour
# (docs/16 §4a). Both are availability and network-path trades, not capability ones —
# every requirement is still met, and each variable's description says exactly what is
# given up.
single_nat_gateway         = true
enable_interface_endpoints = false
