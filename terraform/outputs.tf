# Outputs — docs/08 §3.3.
#
# Deliberately narrow. An output is a public surface: it lands in `terraform output`, in
# CI logs, and in anything that reads the state. Account ids, ARNs, and subnet ids are
# not here, because this repository is public and a pasted output is an easy way to leak
# one (docs/18 §6).

output "app_url" {
  description = "Where the application is. The only URL a person needs."
  value       = local.app_url
}

output "edge" {
  description = "Which service is fronting the application, and whether the viewer hop is encrypted."
  value = {
    kind      = var.edge
    encrypted = local.use_cloudfront || local.alb_https
    # True when visitors will see a certificate warning. Surfaced as an output because it
    # is the kind of thing that is obvious on the day and forgotten a week later.
    self_signed_certificate = local.self_signed
  }
}

output "cloudfront_domain_name" {
  description = "CloudFront domain. Null when the ALB is the edge."
  value       = local.use_cloudfront ? aws_cloudfront_distribution.main[0].domain_name : null
}

output "cognito_user_pool_id" {
  description = "Pool id. Public by construction — it appears in every sign-in URL."
  value       = aws_cognito_user_pool.main.id
}

output "cognito_client_id" {
  description = "App client id. Also public by construction."
  value       = aws_cognito_user_pool_client.spa.id
}

output "cognito_domain" {
  description = "Hosted UI domain prefix."
  value       = aws_cognito_user_pool_domain.main.domain
}

output "backend_ecr_repository" {
  description = "Backend image repository URL, for the build step."
  value       = aws_ecr_repository.backend.repository_url
}

output "frontend_ecr_repository" {
  description = "Frontend image repository URL, for the build step."
  value       = aws_ecr_repository.frontend.repository_url
}

output "litestream_bucket" {
  description = "Replication target, for verifying ADR-007 against the real environment."
  value       = aws_s3_bucket.litestream.id
}
