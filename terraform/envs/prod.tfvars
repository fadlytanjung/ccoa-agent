# Configuration only. **This is never applied** — docs/00 §5, ADR-006 §2.
#
# It exists so that "the design supports a production environment" is a checkable claim
# rather than an assertion, and so the pipeline's gated job has something to reference.
# The job exists and is never approved.
#
# Note what would have to change beyond this file: `min_capacity = 0` is a demo trade
# (the first request after idle gets a 503 while the task cold-starts — see the long
# comment in ecs_backend.tf), and production would run warm. The backend maximum would
# still be 1 until the datastore changes, which is the real ceiling on this design.
environment = "prod"
region      = "ap-southeast-1"

backend_image_tag  = "PLACEHOLDER"
frontend_image_tag = "PLACEHOLDER"

enable_langsmith   = false
log_retention_days = 30

# Full fidelity, unlike dev: no cross-AZ egress dependency, and AWS-service traffic that
# never leaves the VPC. This is the configuration docs/09 argues for, and the reason the
# cheap settings live in tfvars rather than in the resources.
min_capacity = 1

single_nat_gateway         = false
enable_interface_endpoints = true
