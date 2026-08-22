# VPC endpoints — docs/09 §5.2.
#
# Traffic to AWS services stays inside the VPC rather than going out through NAT. Two
# reasons, in order: it removes AWS-service calls from the internet path entirely, and it
# removes them from the NAT bill. The S3 gateway endpoint is free and is what makes ECR
# layer pulls cheap, since layers live in S3.

data "aws_region" "current" {}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = aws_route_table.private[*].id

  tags = { Name = "${local.name}-s3" }
}

locals {
  # ECR needs both: `api` for authentication and metadata, `dkr` for the layers
  # themselves. Configuring one and not the other fails at image pull with an error that
  # points at neither.
  interface_endpoints = {
    ecr_api        = "ecr.api"
    ecr_dkr        = "ecr.dkr"
    logs           = "logs"
    secretsmanager = "secretsmanager"
  }
}

resource "aws_vpc_endpoint" "interface" {
  # Empty when disabled: the tasks then reach ECR, Secrets Manager, and CloudWatch Logs
  # through NAT instead. The S3 gateway endpoint above is unconditional — it is free, and
  # it keeps ECR layer pulls (most of the bytes) off NAT either way.
  for_each = var.enable_interface_endpoints ? local.interface_endpoints : {}

  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${data.aws_region.current.region}.${each.value}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = { Name = "${local.name}-${each.key}" }
}
