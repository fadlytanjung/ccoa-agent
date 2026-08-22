# WAF on CloudFront — docs/08 §3.2.
#
# CloudFront is the only internet-facing surface in this design, so this is the only
# place a WAF would do anything. It must be created in us-east-1 regardless of where the
# rest of the stack lives: the scope is global and the API is served only from there.

resource "aws_wafv2_web_acl" "main" {
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
