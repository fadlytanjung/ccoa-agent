# A self-signed certificate for the ALB — see `var.self_signed_certificate`.
#
# Only created when the ALB is the edge, no ACM ARN was supplied, and the stopgap was
# asked for explicitly. It is never created by default, because a certificate nothing
# vouches for should be a decision somebody made, not something that appeared.

resource "tls_private_key" "self_signed" {
  count = local.self_signed ? 1 : 0

  algorithm = "RSA"
  rsa_bits  = 2048
}

resource "tls_self_signed_cert" "alb" {
  count = local.self_signed ? 1 : 0

  private_key_pem = tls_private_key.self_signed[0].private_key_pem

  subject {
    common_name  = aws_lb.main.dns_name
    organization = "CCOA (development)"
  }

  # Short-lived on purpose. This is a stopgap, and a certificate that quietly works for a
  # year is a stopgap that quietly becomes permanent.
  validity_period_hours = 720 # 30 days

  allowed_uses = ["key_encipherment", "digital_signature", "server_auth"]

  dns_names = [aws_lb.main.dns_name]
}

resource "aws_acm_certificate" "self_signed" {
  count = local.self_signed ? 1 : 0

  private_key      = tls_private_key.self_signed[0].private_key_pem
  certificate_body = tls_self_signed_cert.alb[0].cert_pem

  tags = { Name = "${local.name}-self-signed" }

  lifecycle {
    create_before_destroy = true
  }
}

# --- A certificate a browser trusts ---------------------------------------------------
#
# Only when `domain_name` is set. ACM proves ownership by asking for a DNS record that
# only the zone's owner could create; Terraform writes that record, waits for validation,
# and the certificate is issued without anyone opening a console.
#
# The alternative — the self-signed certificate above — encrypts the same bytes but
# attests nothing, so every visitor is asked to override a warning. Training people to
# click through certificate warnings is its own security problem, which is why this exists
# and why the self-signed path is documented as a stopgap.

data "aws_route53_zone" "main" {
  count = local.managed_certificate ? 1 : 0

  # The apex of the supplied name. `ccoa.example.com` resolves against the `example.com`
  # zone; a bare `example.com` resolves against itself.
  name         = join(".", slice(split(".", var.domain_name), max(0, length(split(".", var.domain_name)) - 2), length(split(".", var.domain_name))))
  private_zone = false
}

resource "aws_acm_certificate" "managed" {
  count = local.managed_certificate ? 1 : 0

  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    # A certificate cannot be detached from a listener and deleted in one step, so the
    # replacement is created first and the old one removed after the switch.
    create_before_destroy = true
  }

  tags = { Name = "${local.name}-managed" }
}

resource "aws_route53_record" "validation" {
  for_each = local.managed_certificate ? {
    for option in aws_acm_certificate.managed[0].domain_validation_options :
    option.domain_name => option
  } : {}

  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = each.value.resource_record_name
  type    = each.value.resource_record_type
  records = [each.value.resource_record_value]
  ttl     = 60

  # Re-applying with an unchanged certificate would otherwise fail on an existing record.
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "managed" {
  count = local.managed_certificate ? 1 : 0

  certificate_arn         = aws_acm_certificate.managed[0].arn
  validation_record_fqdns = [for record in aws_route53_record.validation : record.fqdn]
}

# The domain points at the load balancer. An alias record rather than a CNAME: it works at
# the zone apex, where CNAME is not allowed, and it costs nothing to resolve.
resource "aws_route53_record" "app" {
  count = local.managed_certificate ? 1 : 0

  zone_id = data.aws_route53_zone.main[0].zone_id
  name    = var.domain_name
  type    = "A"

  alias {
    name                   = aws_lb.main.dns_name
    zone_id                = aws_lb.main.zone_id
    evaluate_target_health = true
  }
}
