# WAF — docs/08 §3.2.
#
# The rules are identical for both edges; only the **scope** differs, and the scope is not
# a free choice:
#
#   * `CLOUDFRONT` is a global resource and can only be created in us-east-1, whatever
#     region the rest of the stack lives in.
#   * `REGIONAL` covers ALBs and must be created in the ALB's own region.
#
# Two resources rather than one with a computed scope, because a provider alias cannot be
# selected dynamically — `provider` takes a literal. Duplicating the rules would be worse,
# so they live in a local and are used twice.

locals {
  waf_rules = <<-EOT
    rate limit, AWS common rule set, AWS known-bad-inputs
  EOT
}

resource "aws_wafv2_web_acl" "cloudfront" {
  count    = local.use_cloudfront ? 1 : 0
  provider = aws.us_east_1

  name  = local.name
  scope = "CLOUDFRONT"

  default_action {
    allow {}
  }

  # Rate limiting first, so a flood is dropped before it is inspected by the more
  # expensive managed rules.
  rule {
    name     = "rate-limit"
    priority = 0

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.waf_rate_limit
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "common"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"

        # The SPA POSTs conversation turns up to 4000 characters (docs/06), and the
        # managed body-size rule blocks at 8 KB. Counting rather than blocking keeps the
        # signal without rejecting legitimate messages.
        rule_action_override {
          name = "SizeRestrictions_BODY"
          action_to_use {
            count {}
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "known-bad-inputs"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = local.name
    sampled_requests_enabled   = true
  }

  tags = local.tags
}

resource "aws_wafv2_web_acl" "regional" {
  count = local.use_cloudfront ? 0 : 1

  name  = local.name
  scope = "REGIONAL"

  default_action {
    allow {}
  }

  # Rate limiting first, so a flood is dropped before it is inspected by the more
  # expensive managed rules.
  rule {
    name     = "rate-limit"
    priority = 0

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.waf_rate_limit
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-rate-limit"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "common"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"

        # The SPA POSTs conversation turns up to 4000 characters (docs/06), and the
        # managed body-size rule blocks at 8 KB. Counting rather than blocking keeps the
        # signal without rejecting legitimate messages.
        rule_action_override {
          name = "SizeRestrictions_BODY"
          action_to_use {
            count {}
          }
        }
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-common"
      sampled_requests_enabled   = true
    }
  }

  rule {
    name     = "known-bad-inputs"
    priority = 2

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesKnownBadInputsRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${local.name}-known-bad-inputs"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = local.name
    sampled_requests_enabled   = true
  }

  tags = local.tags
}

# An internet-facing ALB is the only thing between the internet and the listener, so the
# WAF matters *more* here than it does in front of CloudFront, not less.
resource "aws_wafv2_web_acl_association" "alb" {
  count = local.use_cloudfront ? 0 : 1

  resource_arn = aws_lb.main.arn
  web_acl_arn  = aws_wafv2_web_acl.regional[0].arn
}
