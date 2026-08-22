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
