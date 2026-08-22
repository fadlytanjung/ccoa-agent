variable "environment" {
  description = "Environment name. Only `dev` is ever applied (docs/08 §3.1)."
  type        = string

  validation {
    # `demo` and `staging` are explicitly not environments in this project
    # (docs/00 §5). Catching it here beats discovering it in a resource name.
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be `dev` or `prod`."
  }
}

variable "region" {
  description = "AWS region. Singapore, per docs/02 §1."
  type        = string
  default     = "ap-southeast-1"
}

variable "vpc_cidr" {
  description = "VPC range. Must not overlap the account's default VPC (docs/09 §1)."
  type        = string
  default     = "10.0.0.0/16"
}

variable "single_nat_gateway" {
  description = <<-EOT
    Route both private subnets through one NAT gateway instead of one per AZ.

    **A cost choice with an availability cost**, and the two are worth seeing together:
    a second NAT is $0.059/hour — 23% of the idle bill (docs/16 §4) — and what it buys is
    that one AZ losing its NAT does not take the other AZ's egress with it.

    `true` in dev, which is ephemeral and single-purpose. `false` in prod, where the
    dependency would be real. docs/09 §6.3 records the reversal that made this a variable
    rather than a fixed one-per-AZ.
  EOT
  type        = bool
  default     = false
}

variable "enable_interface_endpoints" {
  description = <<-EOT
    Create interface VPC endpoints for ECR, Secrets Manager, and CloudWatch Logs.

    The single largest line on the bill: 4 services x 2 AZs = 8 ENIs at $0.013/hour each,
    **40% of the idle total** (docs/16 §4). What they buy is that AWS-service traffic never
    traverses NAT or the public internet.

    With them off, that traffic goes out through NAT — still over the AWS backbone, still
    TLS, still egress-controlled by the security group, but it does leave the VPC. The
    **S3 gateway endpoint stays either way**: it is free and it carries ECR *layer* pulls,
    which are the bulk of the bytes.
  EOT
  type        = bool
  default     = true
}

variable "backend_image_tag" {
  description = <<-EOT
    Immutable image tag for the backend, normally the commit SHA.
    Never `latest`: it makes rollback ambiguous and a redeploy non-reproducible
    (docs/08 §3.6).
  EOT
  type        = string

  validation {
    condition     = var.backend_image_tag != "latest"
    error_message = "Use an immutable tag (a commit SHA), not `latest`."
  }
}

variable "frontend_image_tag" {
  description = "Immutable image tag for the frontend, normally the commit SHA."
  type        = string

  validation {
    condition     = var.frontend_image_tag != "latest"
    error_message = "Use an immutable tag (a commit SHA), not `latest`."
  }
}

variable "backend_max_capacity" {
  description = <<-EOT
    Maximum backend tasks. **1 is a correctness bound, not tuning.**

    Each task carries its own SQLite copy, so two tasks are two divergent datasets — a
    ticket created on one is invisible to the other (docs/04 §3.5). Litestream also
    corrupts data with more than one writer (ADR-007). Raising this requires changing the
    datastore, not this variable.
  EOT
  type        = number
  default     = 1

  validation {
    condition     = var.backend_max_capacity == 1
    error_message = "The backend must stay at exactly 1 task. See ADR-007 and docs/04 §3.5."
  }
}

variable "frontend_max_capacity" {
  description = "Maximum frontend tasks. Stateless, so this is ordinary tuning."
  type        = number
  default     = 2
}

variable "enable_langsmith" {
  description = <<-EOT
    Send prompts, tool results, and graph state to LangSmith.
    Off by default: it is a third party, and acceptable only because all data is
    synthetic (docs/00 §7).
  EOT
  type        = bool
  default     = false
}

variable "log_retention_days" {
  description = "CloudWatch retention. Finite so `terraform destroy` leaves nothing behind."
  type        = number
  default     = 7
}

variable "waf_rate_limit" {
  description = "Requests per 5 minutes from one IP before WAF blocks it."
  type        = number
  default     = 2000
}
