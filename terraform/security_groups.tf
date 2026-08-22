# Security groups — docs/09 §3, §5.
#
# Every rule is security-group-to-security-group, never a CIDR, except the two places a
# CIDR is unavoidable (endpoint ingress from the VPC, and egress to the internet). A
# CIDR rule keeps allowing traffic after the thing it was written for has moved; an
# SG reference follows the workload.

resource "aws_security_group" "alb" {
  name        = "${local.name}-alb"
  description = "Internal ALB. Ingress only from the CloudFront VPC origin."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-alb" }
}

resource "aws_security_group" "vpc_origin" {
  name        = "${local.name}-vpc-origin"
  description = "CloudFront VPC origin ENIs."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-vpc-origin" }
}

resource "aws_security_group" "backend" {
  name        = "${local.name}-backend"
  description = "Backend tasks. Ingress only from the ALB."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-backend" }
}

resource "aws_security_group" "frontend" {
  name        = "${local.name}-frontend"
  description = "Frontend tasks. Ingress only from the ALB."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-frontend" }
}

resource "aws_security_group" "endpoints" {
  name        = "${local.name}-endpoints"
  description = "Interface VPC endpoints. HTTPS from inside the VPC only."
  vpc_id      = aws_vpc.main.id

  tags = { Name = "${local.name}-endpoints" }
}

# --- ALB ---------------------------------------------------------------------------
# The only ingress the load balancer accepts is from CloudFront's VPC origin ENIs. There
# is no internet-facing listener anywhere in this design (docs/09 §1).
resource "aws_vpc_security_group_ingress_rule" "alb_from_vpc_origin" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.vpc_origin.id
  from_port                    = 80
  to_port                      = 80
  ip_protocol                  = "tcp"
  description                  = "CloudFront VPC origin"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_backend" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.backend.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
  description                  = "Backend target group"
}

resource "aws_vpc_security_group_egress_rule" "alb_to_frontend" {
  security_group_id            = aws_security_group.alb.id
  referenced_security_group_id = aws_security_group.frontend.id
  from_port                    = 8080
  to_port                      = 8080
  ip_protocol                  = "tcp"
  description                  = "Frontend target group"
}

# --- CloudFront VPC origin ----------------------------------------------------------
resource "aws_vpc_security_group_egress_rule" "vpc_origin_to_alb" {
  security_group_id            = aws_security_group.vpc_origin.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 80
  to_port                      = 80
  ip_protocol                  = "tcp"
  description                  = "Internal ALB"
}

# --- Services -----------------------------------------------------------------------
resource "aws_vpc_security_group_ingress_rule" "backend_from_alb" {
  security_group_id            = aws_security_group.backend.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8000
  to_port                      = 8000
  ip_protocol                  = "tcp"
  description                  = "ALB"
}

resource "aws_vpc_security_group_ingress_rule" "frontend_from_alb" {
  security_group_id            = aws_security_group.frontend.id
  referenced_security_group_id = aws_security_group.alb.id
  from_port                    = 8080
  to_port                      = 8080
  ip_protocol                  = "tcp"
  description                  = "ALB"
}

# The backend reaches the Gemini API over the public internet, which is the one egress
# this design genuinely needs (docs/09 §5.2). It cannot be narrowed to a prefix list:
# Google publishes no stable one for the Generative Language API.
resource "aws_vpc_security_group_egress_rule" "backend_https" {
  security_group_id = aws_security_group.backend.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  description       = "Gemini API, S3 replication, AWS endpoints"
}

# The frontend serves static files and calls nothing, so with interface endpoints in place
# it needs no route to the internet at all.
resource "aws_vpc_security_group_egress_rule" "frontend_to_endpoints" {
  count = var.enable_interface_endpoints ? 1 : 0

  security_group_id            = aws_security_group.frontend.id
  referenced_security_group_id = aws_security_group.endpoints.id
  from_port                    = 443
  to_port                      = 443
  ip_protocol                  = "tcp"
  description                  = "Interface endpoints"
}

# Without them, ECR authentication and log delivery go out through NAT, so the frontend
# does need general HTTPS egress. Stated as its own rule rather than folded into the one
# above, so which configuration is in force is legible from the plan.
resource "aws_vpc_security_group_egress_rule" "frontend_https" {
  count = var.enable_interface_endpoints ? 0 : 1

  security_group_id = aws_security_group.frontend.id
  cidr_ipv4         = "0.0.0.0/0"
  from_port         = 443
  to_port           = 443
  ip_protocol       = "tcp"
  description       = "ECR and CloudWatch Logs via NAT"
}

resource "aws_vpc_security_group_egress_rule" "frontend_s3" {
  security_group_id = aws_security_group.frontend.id
  # The S3 gateway endpoint is reached by prefix list, not by SG reference — gateway
  # endpoints have no ENI to point a rule at. This is what makes ECR layer pulls work.
  prefix_list_id = aws_vpc_endpoint.s3.prefix_list_id
  from_port      = 443
  to_port        = 443
  ip_protocol    = "tcp"
  description    = "S3 gateway endpoint (ECR layers)"
}

# --- Interface endpoints -------------------------------------------------------------
resource "aws_vpc_security_group_ingress_rule" "endpoints_from_vpc" {
  security_group_id = aws_security_group.endpoints.id
  # A CIDR is correct here: the callers are ENIs across both private subnets, and the
  # rule is already bounded to this VPC's own range.
  cidr_ipv4   = var.vpc_cidr
  from_port   = 443
  to_port     = 443
  ip_protocol = "tcp"
  description = "HTTPS from inside the VPC"
}
