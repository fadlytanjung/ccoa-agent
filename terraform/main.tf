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

  # docs/09 §1. Public subnets hold NAT and nothing else.
  public_subnet_cidrs  = [cidrsubnet(var.vpc_cidr, 8, 0), cidrsubnet(var.vpc_cidr, 8, 1)]
  private_subnet_cidrs = [cidrsubnet(var.vpc_cidr, 8, 10), cidrsubnet(var.vpc_cidr, 8, 11)]
}
