provider "aws" {
  region = var.region

  # Applied to everything that supports tags, so cost attribution is automatic and the
  # blast radius of `terraform destroy` is verifiable by tag rather than by memory.
  default_tags {
    tags = local.tags
  }
}

# WAF for CloudFront must live in us-east-1 — the scope is global and the API is only
# served from there. Nothing else uses this provider.
provider "aws" {
  alias  = "us_east_1"
  region = "us-east-1"

  default_tags {
    tags = local.tags
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  name = "ccoa-${var.environment}"

  tags = {
    Project     = "ccoa"
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  # Two AZs, deterministically. Sorting means a new AZ appearing in the account cannot
  # silently renumber the subnets and force a rebuild.
  azs = slice(sort(data.aws_availability_zones.available.names), 0, 2)

  nat_count = var.single_nat_gateway ? 1 : length(local.azs)

  use_cloudfront = var.edge == "cloudfront"
  # HTTPS on the ALB path requires a certificate, and a certificate requires a domain.
  # Without one the listener is HTTP, and every URL built below says so rather than
  # printing an https:// that would not work.
  # A managed certificate for a domain you own — the only one a browser trusts.
  managed_certificate = !local.use_cloudfront && var.domain_name != "" && var.acm_certificate_arn == ""

  # A generated certificate counts as HTTPS: the hop is encrypted and, decisively, Cognito
  # will accept the callback URL. It is still a stopgap — see the variable. Only used when
  # there is no domain and no supplied ARN.
  self_signed = (
    !local.use_cloudfront
    && var.acm_certificate_arn == ""
    && var.domain_name == ""
    && var.self_signed_certificate
  )

  alb_https = !local.use_cloudfront && (
    var.acm_certificate_arn != "" || local.managed_certificate || local.self_signed
  )

  certificate_arn = (
    var.acm_certificate_arn != "" ? var.acm_certificate_arn
    : local.managed_certificate ? aws_acm_certificate_validation.managed[0].certificate_arn
    : local.self_signed ? aws_acm_certificate.self_signed[0].arn
    : ""
  )

  # The domain when there is one, the load balancer's own name otherwise. Everything that
  # needs a URL — Cognito callbacks, outputs, the smoke test — reads this.
  alb_host = var.domain_name != "" ? var.domain_name : aws_lb.main.dns_name

  app_url = (
    local.use_cloudfront
    ? "https://${aws_cloudfront_distribution.main[0].domain_name}"
    : "${local.alb_https ? "https" : "http"}://${local.alb_host}"
  )

  # docs/09 §1. Public subnets hold NAT and nothing else.
  public_subnet_cidrs  = [cidrsubnet(var.vpc_cidr, 8, 0), cidrsubnet(var.vpc_cidr, 8, 1)]
  private_subnet_cidrs = [cidrsubnet(var.vpc_cidr, 8, 10), cidrsubnet(var.vpc_cidr, 8, 11)]
}
