# Identity — docs/10 §3.1, §3.1a, ADR-008.
#
# A pool matching this configuration already exists, created by `scripts/aws-cognito.sh`
# before there was anywhere to deploy (see ops-log.md). Import it rather than creating a
# second one:
#
#   terraform import aws_cognito_user_pool.main <pool-id>
#   terraform import aws_cognito_user_pool_client.spa <pool-id>/<client-id>
#   terraform import aws_cognito_user_pool_domain.main <domain-prefix>
#   terraform import 'aws_cognito_user_group.groups["agent"]' <pool-id>/agent
#
# `scripts/deploy.sh --import-cognito` does this.

resource "aws_cognito_user_pool" "main" {
  name = local.name

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length    = 12
    require_uppercase = true
    require_lowercase = true
    require_numbers   = true
    require_symbols   = false
  }

  # The single most important line in this file, and the one whose default is wrong for
  # this project. Cognito defaults to `false`, which lets anyone who reaches the hosted
  # UI create a working account — and here every account can spend the project's model
  # quota, so an open pool is a billing exposure as well as a data one (docs/10 §3.1a).
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  tags = { Name = local.name }
}

resource "aws_cognito_user_group" "groups" {
  for_each = toset(["agent", "supervisor"])

  name         = each.value
  user_pool_id = aws_cognito_user_pool.main.id
  description  = "CCOA ${each.value}"
}

resource "aws_cognito_user_pool_domain" "main" {
  # Globally unique across all of AWS, so it is derived from the pool id rather than
  # fixed — a hardcoded prefix collides for the second person to apply this.
  #
  # A pool id is `<region>_<suffix>`; only the suffix is used, which keeps the prefix
  # short and, more importantly, produces **the same string as `scripts/aws-cognito.sh`**.
  # If the two derivations disagreed, importing the pool that script created would show a
  # domain change — and a domain change is a replacement, taking the hosted UI with it.
  domain       = "ccoa-${lower(element(split("_", aws_cognito_user_pool.main.id), 1))}"
  user_pool_id = aws_cognito_user_pool.main.id
}

resource "aws_cognito_user_pool_client" "spa" {
  name         = "ccoa-spa"
  user_pool_id = aws_cognito_user_pool.main.id

  # **No client secret.** A browser cannot keep one, and a confidential client fails at
  # the token exchange — after a successful-looking sign-in, which makes it a genuinely
  # confusing failure to diagnose (docs/07 §3.4).
  generate_secret = false

  allowed_oauth_flows                  = ["code"] # code + PKCE; never implicit
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  allowed_oauth_flows_user_pool_client = true
  supported_identity_providers         = ["COGNITO"]

  # Both origins, always. `http://localhost` is permitted by Cognito specifically so a SPA
  # can be developed against real identities, and keeping it registered is what lets the
  # deployed pool be used from a laptop (docs/18 §7).
  callback_urls = [
    "https://${aws_cloudfront_distribution.main.domain_name}/callback",
    "http://localhost:5173/callback",
  ]
  logout_urls = [
    "https://${aws_cloudfront_distribution.main.domain_name}",
    "http://localhost:5173",
  ]

  # An hour of work without re-authenticating, and a refresh token that expires in a day
  # rather than the 30-day default — this is an operations console, not a consumer app.
  access_token_validity  = 60
  id_token_validity      = 60
  refresh_token_validity = 1

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  # Refresh rotation would invalidate the session held in memory by an open tab.
  enable_token_revocation = true
}
