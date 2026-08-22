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

# --- Cost ---------------------------------------------------------------------------
# Together these remove ~63% of the idle bill: ~$0.26/hour becomes ~$0.09/hour
# (docs/16 §4a). Both are availability and network-path trades, not capability ones —
# every requirement is still met, and each variable's description says exactly what is
# given up.
single_nat_gateway         = true
enable_interface_endpoints = false
