# CloudFront — docs/08 §3.5.
#
# The only internet-facing resource in the project. It terminates TLS with CloudFront's
# own `*.cloudfront.net` certificate, so there is no domain to buy and no ACM certificate
# to validate (docs/00 §6), and reaches the internal ALB over a VPC origin.

resource "aws_cloudfront_vpc_origin" "alb" {
  vpc_origin_endpoint_config {
    name                   = local.name
    arn                    = aws_lb.main.arn
    http_port              = 80
    https_port             = 443
    origin_protocol_policy = "http-only" # TLS ends at the edge; this hop is inside the VPC

    origin_ssl_protocols {
      items    = ["TLSv1.2"]
      quantity = 1
    }
  }

  tags = { Name = local.name }
}

resource "aws_cloudfront_distribution" "main" {
  enabled         = true
  is_ipv6_enabled = true
  comment         = local.name
  price_class     = "PriceClass_200" # includes ap-southeast-1
  web_acl_id      = aws_wafv2_web_acl.main.arn

  origin {
    origin_id   = "alb"
    domain_name = aws_lb.main.dns_name

    vpc_origin_config {
      vpc_origin_id = aws_cloudfront_vpc_origin.alb.id
    }
  }

  # --- The API. This behaviour is the highest-risk configuration in the design ---------
  #
  # Caching a `/api/*` response would serve one agent's answer — including another
  # customer's records — to a different agent. `CachingDisabled` is therefore not a
  # performance choice, and `AllViewer` is what carries the `Authorization` header
  # through; without it every request arrives unauthenticated and the API returns 401
  # for everyone. docs/09 §8 requires this to be asserted by a test, not merely set here.
  ordered_cache_behavior {
    path_pattern             = "/api/*"
    target_origin_id         = "alb"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled.id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer.id
    compress                 = true
  }

  # --- Hashed assets: safe to cache hard, because the name changes when the bytes do ---
  ordered_cache_behavior {
    path_pattern           = "/assets/*"
    target_origin_id       = "alb"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.optimized.id
    compress               = true
  }

  # --- Everything else is index.html, which must never be cached: it is what points at
  # the hashed assets, and a stale copy pins the whole app to a previous deploy ---------
  default_cache_behavior {
    target_origin_id       = "alb"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = data.aws_cloudfront_cache_policy.disabled.id
    compress               = true
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
    minimum_protocol_version       = "TLSv1.2_2021"
  }

  tags = { Name = local.name }
}

data "aws_cloudfront_cache_policy" "disabled" {
  name = "Managed-CachingDisabled"
}

data "aws_cloudfront_cache_policy" "optimized" {
  name = "Managed-CachingOptimized"
}

data "aws_cloudfront_origin_request_policy" "all_viewer" {
  name = "Managed-AllViewer"
}
